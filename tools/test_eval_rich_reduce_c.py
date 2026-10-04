#!/usr/bin/env python3
"""Original post-storage physical REF/RREF leaves versus readable C.

The original oracle executes16538 through16588, including captured-context
cleanup. The generated test adapter calls the actual public rich dispatch
API; its owned integration applies cleanup once. Allocation and restaging are absent.
Only the scalar arithmetic arena and witnessed native CPU-frame writes are
excluded from persistent RAM comparison; every physical bank and MMIO byte
remains observable. GPL-3.0-only.
"""
import argparse
import base64
import gzip
import sys
from datetime import datetime, timezone
from pathlib import Path
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


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]


class NumericContext(C.Structure):
    _fields_ = [('exact_math', C.c_uint8), ('display_mode', C.c_uint8),
                ('digits', C.c_uint8), ('cancel_at', C.c_uint32)]


class Context(C.Structure):
    _fields_ = [('calculation_context', C.c_uint8), ('numeric', NumericContext),
                ('cancelled', C.c_void_p), ('userdata', C.c_void_p)]


class Result(C.Structure):
    _fields_ = [('value', Complex), ('other', Complex),
                ('firmware_status', C.c_uint8), ('cancellation_checks', C.c_uint32)]


class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
                ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64),
                ('flags', C.c_uint8)]


# The shared poll belongs to fx_eval_rich.c. Its linked dispatch functions
# require this explicit target; the transitive local headers are pinned too.
SOURCES = ['parse/fx_eval_rich_reduce.c', 'parse/fx_eval_rich.c',
           'parse/fx_eval_rich_unary.c', 'parse/fx_eval_surd_workspace.c',
           'platform/fx_platform.c', 'platform/fx_result_classify.c',
           'linalg/fx_linalg.c', 'complex/fx_complex_dispatch.c',
           'complex/fx_complex.c', 'complex/fx_complex_angle.c',
           'complex/fx_complex_round.c', 'numeric/fx_numeric.c',
           'numeric/fx_surd_components.c',
           'numeric/fx_transcend.c', 'numeric/fx_power.c', 'numeric/fx_root.c',
           'numeric/fx_combinatorics.c', 'numeric/fx_logbase.c',
           'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c',
           'trig/fx_trig_hyperbolic.c', 'numeric/fx_raw_decimal_parts.c',
           'numeric/fx_raw_decimal_divide.c',
           'numeric/fx_raw_decimal_multiply_add.c',
           'numeric/fx_raw_fraction_convert.c', 'numeric/fx_raw_decimal_exp.c']

# Individually retained full default inputs, not a blanket surd/slot exclusion.
# Each must additionally match persistent RAM and poll count at a native1CCF6
# entry whose live opposite-sign compact source overlaps the component pool.
SEEDED_CLASSIFIER_BOUNDARIES = {
    '5900b80cdb3a93bd434d1abaeda5f4c1be1e8dea73e939b1d788da3e6f4ece96',
    'b9aa13ab757ba7c5671416d9b12988607fa577345ecd3424b7f5f2e8600785f6',
}

ADAPTER = r'''
#include "parse/fx_eval_rich.h"
#include <string.h>
int reduce_test_dispatch(fx_eval_rich_result *out, fx_eval_storage *storage,
    unsigned pair, unsigned selector, const fx_eval_rich_context *context,
    unsigned private_pair)
{
    fx_complex current,other;
    fx_numeric_status status;
    if (!private_pair)
        return fx_eval_rich_dispatch_address(out,storage,(uint16_t)pair,
            (uint8_t)selector,context);
    memcpy(&current,storage->ram+pair,sizeof current);
    memcpy(&other,storage->ram+pair+20u,sizeof other);
    status=fx_eval_rich_dispatch(out,storage,&current,&other,
        (uint8_t)selector,context);
    if (status!=FX_NUMERIC_OK) return status;
    if (status==FX_NUMERIC_OK) {
        memcpy(storage->ram+pair,&out->value,sizeof out->value);
        memcpy(storage->ram+pair+20u,&out->other,sizeof out->other);
    }
    return status;
}
'''

ADAPTER += r'''
#include <stddef.h>
size_t reduce_test_abi(unsigned i) {
    static const size_t a[] = {
        sizeof(fx_number), offsetof(fx_number,bytes),
        sizeof(fx_complex), offsetof(fx_complex,real), offsetof(fx_complex,imaginary),
        sizeof(fx_linalg_context), offsetof(fx_linalg_context,exact_math), offsetof(fx_linalg_context,display_mode), offsetof(fx_linalg_context,digits), offsetof(fx_linalg_context,cancel_at),
        sizeof(fx_eval_rich_context), offsetof(fx_eval_rich_context,calculation_context), offsetof(fx_eval_rich_context,numeric), offsetof(fx_eval_rich_context,cancelled), offsetof(fx_eval_rich_context,userdata),
        sizeof(fx_eval_rich_result), offsetof(fx_eval_rich_result,value), offsetof(fx_eval_rich_result,other), offsetof(fx_eval_rich_result,firmware_status), offsetof(fx_eval_rich_result,cancellation_checks),
        sizeof(fx_eval_storage), offsetof(fx_eval_storage,ram), offsetof(fx_eval_storage,ram_size), offsetof(fx_eval_storage,rom), offsetof(fx_eval_storage,rom_size),
        sizeof(fx_rational), offsetof(fx_rational,numerator), offsetof(fx_rational,denominator), offsetof(fx_rational,flags)
    };
    return i < sizeof(a)/sizeof(a[0]) ? a[i] : (size_t)-1;
}
'''

ORACLE = r'''
#include "harness.c"
unsigned reduce_polls,reduce_minimum_sp,reduce_target;
unsigned reduce_observe_callbacks,reduce_mutation_count;
unsigned reduce_poll_caller[256];
unsigned reduce_observe_prefix,reduce_prefix_count;
unsigned reduce_prefix_pc[256],reduce_prefix_poll[256],reduce_prefix_sp[256];
unsigned reduce_prefix_kind[256],reduce_prefix_source[256];
uint8_t reduce_prefix_memory[256][65536],reduce_prefix_frame_writes[256][65536];
unsigned reduce_mutation_poll[8],reduce_mutation_address[8],reduce_mutation_size[8];
uint8_t reduce_mutation_bytes[8][20];
uint8_t reduce_poll_memory[256][65536],reduce_poll_frame_writes[256][65536];
unsigned reduce_allocator_visits;
int reduce_run(unsigned selector,unsigned pair,unsigned cancel)
{
    harness_set_sp(0x8dee); harness_set_pc(0x16538); harness_set_lr(0x2fffe);
    harness_set_reg(1,selector); harness_set_reg(12,pair&255);
    harness_set_reg(13,pair>>8);
    reduce_polls=reduce_target=reduce_allocator_visits=reduce_prefix_count=0;
    reduce_minimum_sp=0x8dee;
    for (uint64_t n=0;n<20000000;++n) {
        uint32_t pc=harness_get_pc(); unsigned sp=harness_get_sp();
        if (sp<reduce_minimum_sp) reduce_minimum_sp=sp;
        if (pc==0x16588) return 100;
        if (pc==0x163f0) ++reduce_allocator_visits;
        if (pc==0x1655c)
            reduce_target=0x10000u|harness_get_reg(4)|(unsigned)harness_get_reg(5)<<8;
        if (pc==0x5550 && reduce_polls<256)
            reduce_poll_caller[reduce_polls]=((unsigned)LCSR<<16)|LR;
        if (reduce_observe_prefix && (pc==0x1ca3e || pc==0x15c82 || pc==0x1ccf6)) {
            unsigned a=harness_get_reg(0)|(unsigned)harness_get_reg(1)<<8;
            unsigned b=harness_get_reg(2)|(unsigned)harness_get_reg(3)<<8;
            unsigned malformed=0,kind=0,source_address=a;
            if (pc==0x1ccf6 && a>=0x8637 && a<0x867c &&
                (ram[a]&0xf0u)==0x80 && ram[a+9] &&
                (uint8_t)(ram[a+8]+ram[a+9])==7) { malformed=1; kind=2; }
            for (unsigned k=0;k<(pc==0x1ca3e ? 2u : pc==0x15c82 ? 1u : 0u);++k) {
                unsigned source=k ? b : a;
                if (source>65526 || (ram[source]&0xb0u)!=0x20) continue;
                unsigned zero=1;
                for (unsigned j=1;j<8;++j) if (ram[source+j]) zero=0;
                if (zero) { malformed=1; kind=1; source_address=source; }
            }
            if (malformed) {
                unsigned index=reduce_prefix_count++;
                if (index>=256) return 106;
                reduce_prefix_pc[index]=pc; reduce_prefix_poll[index]=reduce_polls;
                reduce_prefix_sp[index]=reduce_minimum_sp;
                reduce_prefix_kind[index]=kind; reduce_prefix_source[index]=source_address;
                memcpy(reduce_prefix_memory[index],ram,65536);
                memset(reduce_prefix_frame_writes[index],0,65536);
                for (unsigned address=reduce_minimum_sp;address<0x8df0;++address)
                    reduce_prefix_frame_writes[index][address]=(uint8_t)(ram_write_counts[address]!=0);
            }
        }
        if (pc==0x5564) {
            unsigned index=reduce_polls++;
            if (index>=256) return 105;
            if (reduce_observe_callbacks) {
                memcpy(reduce_poll_memory[index],ram,65536);
                memset(reduce_poll_frame_writes[index],0,65536);
                for (unsigned a=reduce_minimum_sp;a<0x8df0;++a)
                    reduce_poll_frame_writes[index][a]=(uint8_t)(ram_write_counts[a]!=0);
            }
            for (unsigned i=0;i<reduce_mutation_count;++i)
                if (reduce_mutation_poll[i]==reduce_polls)
                    memcpy(ram+reduce_mutation_address[i],reduce_mutation_bytes[i],
                        reduce_mutation_size[i]);
            ram[0x8e00]=(uint8_t)(cancel && reduce_polls==cancel);
        }
        int status=harness_run(1,0x2fffe,false);
        if (status!=103) return status;
    }
    return 103;
}
'''


WIDE_INPUT = 'analysis/native-fixtures/eval-rich/reduce/wide-inputs.json'


def local_python_inputs():
    modules = {}
    own = Path(__file__).resolve().parent
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix == '.py' and (path.is_relative_to(ROOT) or path.is_relative_to(own)):
            modules[name] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    for name in ('__main__', 'c_build_inputs', 'c_verification', 'nxu8.machine'):
        assert name in modules, ('Unpinned executed Python module', name)
    return dict(sorted(modules.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=2000)
    parser.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--only-label', action='append', default=[],
                        help='Diagnostic subset; requires --no-report')
    parser.add_argument('--wide-input', type=Path,
                        help='Private input preview; requires --no-report')
    parser.add_argument('--build-dir', type=Path,
                        help='Private artifact location; requires --no-report')
    args = parser.parse_args()
    if (args.wide_input or args.build_dir) and not args.no_report:
        parser.error('--wide-input/--build-dir require --no-report')
    wide_path = args.wide_input.resolve() if args.wide_input else ROOT/WIDE_INPUT
    fixture = json.loads(wide_path.read_text())
    allowed = {'id','label','selector','identity','requested_context','requested_shape','kind',
               'cancel','callback','pair','private_pair','initial_payload90','initial_pair40',
               'initial_ram_sha256','mutations'}
    wide_cases = fixture['cases']
    if fixture['schema'] != 'prepared-rich-wide-inputs-v1' or len(wide_cases) != 1215:
        raise ValueError('Expected1215 retained wide input-only recipes')
    if any(set(case) != allowed for case in wide_cases):
        raise ValueError('Wide fixture contains fields outside the input-only recipe')
    if [case['id'] for case in wide_cases] != list(range(1215)):
        raise ValueError('Wide fixture IDs must be consecutive')
    for case in wide_cases:
        rows,columns = case['requested_shape']
        if rows not in (1,2) or not 4 <= columns <= (9 if rows == 1 else 6):
            raise ValueError('Wide fixture outside sufficient literal nine-record domain')
        if case['selector'] not in (16,17) or len(bytes.fromhex(case['initial_payload90'])) != 90 or len(bytes.fromhex(case['initial_pair40'])) != 40:
            raise ValueError('Invalid wide numerical input recipe')
    python_modules_start = local_python_inputs()
    if args.random_cases < 0:
        parser.error('--random-cases must be nonnegative')
    if args.random_cases < 2000 and not args.no_report:
        parser.error('Fewer than2000 random cases requires --no-report')
    if args.only_label and not args.no_report:
        parser.error('--only-label requires --no-report; subsets cannot publish proof')
    inputs = implementation_inputs(ROOT, ['csrc/' + path for path in SOURCES])
    dependencies = inputs + ['tools/test_eval_rich_reduce_c.py',
        'tools/c_build_inputs.py', 'tools/c_verification.py', 'tools/nxu8/machine.py',
        'tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
        'firmware/fx-991es-plus-c-ver4.bin']
    dependencies += [str(path.relative_to(ROOT))
                     for path in sorted((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))]
    dependencies += list(python_modules_start.values())
    dependencies += [str(wide_path.relative_to(ROOT)) if wide_path.is_relative_to(ROOT) else str(wide_path)]
    dependencies = list(dict.fromkeys(dependencies))
    start_hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                    for name in dependencies}
    build = args.build_dir.resolve() if args.build_dir else ROOT/'analysis/build/eval-rich-reduce'
    build.mkdir(parents=True, exist_ok=True)
    adapter = build / ('adapter-' + args.optimization + '.c')
    adapter.write_text(ADAPTER)
    library = build / ('reduce-' + args.optimization + '.so')
    subprocess.run(['gcc', '-std=c99', '-' + args.optimization, '-Wall', '-Wextra',
                    '-Werror', '-pedantic', '-shared', '-fPIC', '-Wl,--no-undefined',
                    '-I', str(ROOT/'csrc'),
                    str(adapter), *[str(ROOT/'csrc'/p) for p in SOURCES],
                    '-o', str(library)], check=True)
    implementation = C.CDLL(str(library))
    implementation.reduce_test_abi.argtypes = [C.c_uint]
    implementation.reduce_test_abi.restype = C.c_size_t
    expected_abi = [C.sizeof(Number), Number.bytes.offset,
        C.sizeof(Complex), Complex.real.offset, Complex.imaginary.offset,
        C.sizeof(NumericContext), NumericContext.exact_math.offset, NumericContext.display_mode.offset,
        NumericContext.digits.offset, NumericContext.cancel_at.offset,
        C.sizeof(Context), Context.calculation_context.offset, Context.numeric.offset,
        Context.cancelled.offset, Context.userdata.offset,
        C.sizeof(Result), Result.value.offset, Result.other.offset,
        Result.firmware_status.offset, Result.cancellation_checks.offset,
        C.sizeof(Storage), Storage.ram.offset, Storage.ram_size.offset, Storage.rom.offset, Storage.rom_size.offset,
        C.sizeof(Rational), Rational.numerator.offset, Rational.denominator.offset, Rational.flags.offset]
    actual_abi = [implementation.reduce_test_abi(i) for i in range(len(expected_abi))]
    if actual_abi != expected_abi:
        raise AssertionError(('Public ctypes/C ABI mismatch',actual_abi,expected_abi))
    implementation.reduce_test_dispatch.argtypes = [C.POINTER(Result), C.POINTER(Storage),
        C.c_uint, C.c_uint, C.POINTER(Context), C.c_uint]
    implementation.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    implementation.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    implementation.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    implementation.fx_number_to_decimal.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    oracle_dir = build / ('oracle-' + args.optimization)
    oracle_dir.mkdir(exist_ok=True)
    oracle = oracle_dir / 'reduce-observer.c'
    oracle.write_text(ORACLE)
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-I', str(ROOT/'tools/nxu8'), str(oracle),
                    str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(oracle_dir/'nxu8-harness.so')], check=True)
    machine = Machine(rom, oracle_dir)
    machine.lib.reduce_run.argtypes = [C.c_uint, C.c_uint, C.c_uint]
    rom_buffer = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    counts, labels, failures, gaps = Counter(), Counter(), [], []
    native_calls = 0
    observations = []
    wide_snapshots = []
    rng = random.Random(0x1477614786)

    def decimal(value):
        number = Number()
        assert implementation.fx_decimal_parse(C.byref(number), str(value).encode()) == 0
        return bytes(number)

    def rational(numerator, denominator):
        number = Number()
        assert implementation.fx_rational_encode(C.byref(number),
            C.byref(Rational(numerator, denominator, 0))) == 0
        return bytes(number)

    def surd(components):
        number = Number()
        parts = (Number * 6)(*[Number.from_buffer_copy(decimal(x)) for x in components])
        assert implementation.fx_surd_pack(C.byref(number), parts) == 0
        return bytes(number)

    zero = bytes(10)
    integers = [decimal(x) for x in (-9, -3, -1, 0, 1, 2, 3, 7, 99)]
    ordinary = [decimal(x) for x in ('1e-99', '1e-12', '1e-11', '1e-10',
        '1.00000000000001', '0.999999999999999', '-1.23456789012345', '1e99')]
    exact = [rational(1, 3), rational(-2, 7), rational(5, 2),
             surd((1, 2, 1, 0, 1, 1)), surd((-1, 3, 2, 1, 5, 3))]
    errors = [bytes([x]) + bytes(9) for x in (0xf0, 0xf1, 0xf3, 0xf7, 0xff)]
    marked = [bytes([x[0] | 0x40]) + x[1:] for x in integers + exact[:3]]
    cells = [decimal(i + 1) for i in range(9)]

    def check(group, expected, actual, detail):
        counts[group] += 1
        if expected != actual:
            failures.append(dict(group=group, expected=expected, actual=actual, **detail))
            if len(failures) <= 15:
                compact = dict(failures[-1])
                for field in ('expected', 'actual'):
                    if isinstance(compact[field], str) and len(compact[field]) > 200:
                        compact[field] = compact[field][:200]+'...'
                print(json.dumps(compact), flush=True)

    def memory_check(group, expected, actual, detail, frame_writes, minimum_sp):
        expected = bytearray(expected)
        expected[0x8000:0x80dc] = actual[0x8000:0x80dc]
        for address in range(minimum_sp, 0x8df0):
            if frame_writes[address]:
                expected[address] = actual[address]
        if expected == actual:
            check(group, True, True, detail)
            return
        differences = [dict(address=f'{a:04x}', native=n, c=actual[a])
                       for a, n in enumerate(expected) if n != actual[a]]
        check(group, [], differences[:20], dict(difference_count=len(differences), **detail))

    def case(selector, context=6, identity=4, shape=(3, 3), data=None,
             kind=6, imaginary=zero, other_real=None, other_imaginary=None,
             cancel=0, callback=False, mutations=(), label='', pair=0x8a00,
             private_pair=False, host_gap=None, updates=(), input_hash=None, fixture_id=None):
        nonlocal native_calls
        if args.only_label and label not in args.only_label:
            return
        labels[label] += 1
        memory = bytearray(65536)
        for slot in range(16):
            base = 0x829e + 90*slot
            memory[base:base+90] = b''.join(decimal(9*slot+i+1) for i in range(9))
        # Globals precede dimensions; identity12's column aliases80F9. The
        # actual captured context and dimensions below always come from RAM.
        memory[0x80f9] = context
        memory[0x8106] = 1
        memory[0x8125] = 0x98
        dimensions, base = 0x80e0+2*identity, 0x829e+90*identity
        memory[dimensions:dimensions+2] = bytes(shape)
        memory[base:base+90] = b''.join(data or cells)
        current = bytes([kind*16+identity]) + bytes(9) + imaginary
        other = (decimal(-7) if other_real is None else other_real)
        other += decimal(9) if other_imaginary is None else other_imaginary
        memory[pair:pair+40] = current + other
        for address, record in updates:
            memory[address:address+len(record)] = record
        initial = bytes(memory)
        initial_hash=hashlib.sha256(initial).hexdigest()
        if input_hash and initial_hash != input_hash:
            raise AssertionError(('Literal wide input reconstruction mismatch',fixture_id,initial_hash,input_hash))
        prefix_expected_kind=2 if label=='ordered-classifier-pool-alias-boundary' else (
            1 if label in ('unchecked-zero-denominator','callback-malformed-fraction-boundary') else 0)
        if initial_hash in SEEDED_CLASSIFIER_BOUNDARIES:
            assert callback and not host_gap
            host_gap='Individually retained seeded input reaches the opposite-sign physical classifier component-pool alias'
            prefix_expected_kind=2
        actual_context = memory[0x80f9]
        actual_shape = tuple(memory[dimensions:dimensions+2])
        exact_permission = bool(actual_context & 0x40 and memory[0x8106] and
            memory[0x810c] != 1 and not memory[0x80fc] & 0x40 and
            memory[0x80f5] != 0xed and not memory[0x8124] & 1)
        numerical = Context(actual_context, NumericContext(exact_permission,
            memory[0x8102], memory[0x8103], 0 if callback else cancel))
        snapshots, userdata_values = [], []
        userdata = C.c_uint32(0x14776147)
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p)

        @callback_type
        def sample_cancel(pointer):
            snapshots.append(bytes(memory))
            userdata_values.append(C.cast(pointer, C.POINTER(C.c_uint32))[0])
            for poll, address, record in mutations:
                if poll == len(snapshots):
                    memory[address:address+len(record)] = record
            return bool(cancel and len(snapshots) == cancel)

        if callback:
            numerical.cancelled = C.cast(sample_cancel, C.c_void_p).value
            numerical.userdata = C.cast(C.byref(userdata), C.c_void_p).value
        assert len(mutations) <= 8 and all(0 < len(record) <= 20 for _, _, record in mutations)
        assert not mutations or callback
        if private_pair:
            assert all(not (address < pair+40 and address+len(record) > pair)
                       for _, address, record in mutations), 'Host-private pair mutations require physical address mode'
        machine.reset()
        C.memmove(C.addressof(machine.ram), initial, 65536)
        C.c_uint.in_dll(machine.lib, 'reduce_observe_callbacks').value = int(callback)
        C.c_uint.in_dll(machine.lib, 'reduce_observe_prefix').value = int(bool(host_gap))
        C.c_uint.in_dll(machine.lib, 'reduce_mutation_count').value = len(mutations)
        polls = (C.c_uint*8).in_dll(machine.lib, 'reduce_mutation_poll')
        addresses = (C.c_uint*8).in_dll(machine.lib, 'reduce_mutation_address')
        sizes = (C.c_uint*8).in_dll(machine.lib, 'reduce_mutation_size')
        records = ((C.c_uint8*20)*8).in_dll(machine.lib, 'reduce_mutation_bytes')
        for index, (poll, address, record) in enumerate(mutations):
            assert 0 <= address <= 65536-len(record)
            polls[index], addresses[index], sizes[index] = poll, address, len(record)
            C.memmove(records[index], record, len(record))
        stopped = machine.lib.reduce_run(selector, pair, cancel)
        native_calls += 1
        detail = dict(label=label, selector=selector, identity=identity,
            requested_context=context, context=actual_context, requested_shape=shape,
            shape=actual_shape, kind=kind, cancel=cancel, callback=callback,
            numeric_cancel_at=numerical.numeric.cancel_at,
            pair=f'{pair:04x}', private_pair=private_pair,
            initial_payload90=initial[base:base+90].hex(),
            initial_pair40=initial[pair:pair+40].hex(),
            initial_dimensions32=initial[0x80e0:0x8100].hex(),
            initial_ram_sha256=initial_hash,
            mutations=[dict(poll=p, address=f'{a:04x}', record=r.hex()) for p, a, r in mutations])
        detail['fixture_id'] = fixture_id
        observation = dict(id=native_calls-1, **detail,
            native_stop=stopped, native_status=machine.reg(0),
            native_current20=bytes(machine.ram[pair:pair+20]).hex(),
            native_other20=bytes(machine.ram[pair+20:pair+40]).hex(),
            native_final_ram_sha256=hashlib.sha256(bytes(machine.ram)).hexdigest())
        observations.append(observation)
        check('original_stop', 100, stopped, detail)
        if stopped != 100:
            return
        target = C.c_uint.in_dll(machine.lib, 'reduce_target').value
        table = 0x291e + ((selector*2)&255)
        check('actual_original_table_leaf', 0x10000 | rom[table] | rom[table+1]<<8,
              target, detail)
        check('no_original_storage_stage', 0,
              C.c_uint.in_dll(machine.lib, 'reduce_allocator_visits').value, detail)
        native_polls = C.c_uint.in_dll(machine.lib, 'reduce_polls').value
        buffer = (C.c_uint8*65536).from_buffer(memory)
        storage = Storage(buffer, 65536, rom_buffer, len(rom))
        output = Result()
        C.memset(C.byref(output), 0xad, C.sizeof(output))
        host = implementation.reduce_test_dispatch(C.byref(output), C.byref(storage),
            pair, selector, C.byref(numerical), private_pair)
        native_states=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_poll_memory')
        observation.update(host_status=host, native_polls=native_polls,
            actual_current20=bytes(output.value).hex(), actual_other20=bytes(output.other).hex(),
            actual_status=output.firmware_status, actual_polls=output.cancellation_checks,
            actual_final_ram_sha256=hashlib.sha256(memory).hexdigest(),
            native_callback_ram_sha256=[hashlib.sha256(bytes(native_states[i])).hexdigest() for i in range(native_polls)] if callback else [],
            actual_callback_ram_sha256=[hashlib.sha256(x).hexdigest() for x in snapshots])
        if fixture_id is not None:
            check('literal_wide_input_reconstruction',input_hash,initial_hash,detail)
            wide_snapshots.append(dict(id=fixture_id,native_final_ram_b64=base64.b64encode(bytes(machine.ram)).decode(),
                actual_final_ram_b64=base64.b64encode(memory).decode()))
        if host_gap:
            check('explicit_architectural_host_gap', -3, host, dict(reason=host_gap, **detail))
            check('host_gap_output_noncommit', 'ad'*C.sizeof(output), bytes(output).hex(), detail)
            native=bytes(machine.ram)
            boundary=dict(reason=host_gap, native_status=machine.reg(0), native_polls=native_polls,
                native_current20=native[pair:pair+20].hex(), native_other20=native[pair+20:pair+40].hex(),
                native_payload1440=native[0x829e:0x883e].hex(),
                native_ram_sha256=hashlib.sha256(native).hexdigest(), **detail)
            if prefix_expected_kind:
                prefix_count=C.c_uint.in_dll(machine.lib,'reduce_prefix_count').value
                prefix_memory=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_prefix_memory')
                prefix_frames=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_prefix_frame_writes')
                prefix_polls=(C.c_uint*256).in_dll(machine.lib,'reduce_prefix_poll')
                prefix_pcs=(C.c_uint*256).in_dll(machine.lib,'reduce_prefix_pc')
                prefix_sp=(C.c_uint*256).in_dll(machine.lib,'reduce_prefix_sp')
                prefix_kind=(C.c_uint*256).in_dll(machine.lib,'reduce_prefix_kind')
                prefix_source=(C.c_uint*256).in_dll(machine.lib,'reduce_prefix_source')
                matched=None
                for index in range(prefix_count):
                    if prefix_polls[index] != len(snapshots): continue
                    if prefix_kind[index]!=prefix_expected_kind: continue
                    candidate=bytearray(prefix_memory[index])
                    candidate[0x8000:0x80dc]=memory[0x8000:0x80dc]
                    for address in range(prefix_sp[index],0x8df0):
                        if prefix_frames[index][address]: candidate[address]=memory[address]
                    if candidate==memory:
                        matched=index; break
                check('host_gap_persistent_RAM_at_native_kernel_entry',True,matched is not None,detail)
                if matched is None:
                    diagnostic=[]
                    for index in range(prefix_count):
                        candidate=bytearray(prefix_memory[index])
                        candidate[0x8000:0x80dc]=memory[0x8000:0x80dc]
                        for address in range(prefix_sp[index],0x8df0):
                            if prefix_frames[index][address]: candidate[address]=memory[address]
                        differences=[dict(address=f'{address:04x}',native=n,c=memory[address])
                            for address,n in enumerate(candidate) if n!=memory[address]]
                        diagnostic.append(dict(pc=f'{prefix_pcs[index]:06x}',polls=prefix_polls[index],
                            kind=prefix_kind[index],source=f'{prefix_source[index]:04x}',
                            difference_count=len(differences),differences=differences[:20]))
                    boundary['unmatched_native_boundary_candidates']=diagnostic
                    boundary['c_boundary_polls']=len(snapshots)
                    (build/f"unmatched-{selector}-{initial[0x80f9]}-{hashlib.sha256(initial).hexdigest()[:12]}.bin").write_bytes(memory)
                if matched is not None:
                    boundary['native_boundary_pc']=f'{prefix_pcs[matched]:06x}'
                    boundary['native_boundary_polls']=prefix_polls[matched]
                    boundary['native_boundary_ram_sha256']=hashlib.sha256(bytes(prefix_memory[matched])).hexdigest()
                    source=prefix_source[matched]
                    boundary['native_boundary_source']=f'{source:04x}'
                    boundary['native_boundary_source10']=bytes(prefix_memory[matched][source:source+10]).hex()
                native_states=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_poll_memory')
                frame_writes=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_poll_frame_writes')
                for index,actual in enumerate(snapshots):
                    memory_check('host_gap_callback_persistent_RAM_before_answer',bytes(native_states[index]),
                        actual,dict(poll=index+1,**detail),frame_writes[index],C.c_uint.in_dll(machine.lib,'reduce_minimum_sp').value)
            observation['boundary'] = boundary
            gaps.append(boundary)
            return
        check('host_status', 0, host, detail)
        if host != 0:
            return native_polls
        native = bytes(machine.ram)
        minimum_sp = C.c_uint.in_dll(machine.lib, 'reduce_minimum_sp').value
        check('current20', native[pair:pair+20].hex(), bytes(output.value).hex(), detail)
        check('other20', native[pair+20:pair+40].hex(), bytes(output.other).hex(), detail)
        check('native_status', machine.reg(0), output.firmware_status, detail)
        check('poll_count', native_polls, output.cancellation_checks, detail)
        check('temporary_mask', native[0x8125], memory[0x8125], detail)
        check('dimensions32', native[0x80e0:0x8100].hex(), memory[0x80e0:0x8100].hex(), detail)
        check('physical_payload1440', native[0x829e:0x883e].hex(),
              memory[0x829e:0x883e].hex(), detail)
        memory_check('remaining_persistent_RAM', native, memory, detail,
                     machine.ram_writes, minimum_sp)
        if callback:
            check('callback_count', native_polls, len(snapshots), detail)
            check('callback_userdata', [0x14776147]*native_polls, userdata_values, detail)
            native_states = ((C.c_uint8*65536)*256).in_dll(machine.lib, 'reduce_poll_memory')
            frame_writes = ((C.c_uint8*65536)*256).in_dll(machine.lib, 'reduce_poll_frame_writes')
            assert len(snapshots) <= 256
            for index, actual in enumerate(snapshots):
                memory_check('callback_persistent_RAM_before_answer', bytes(native_states[index]),
                    actual, dict(poll=index+1, **detail), frame_writes[index], minimum_sp)
        return native_polls

    fixtures = [
        [1, 2, 97, 3, 4, 98, 95, 96, 99],
        [1, 0, 2, 0, 0, 1, 0, 0, 3],
        [0, 1, 2, 0, 1, 4, 0, 0, 0],
        [0, 0, 1, 0, 2, 3, 4, 5, 6],
        [1, 2, 3, 2, 4, 6, 3, 6, 9],
        [0]*9, [1, 0, 0, 0, 1, 0, 0, 0, 1],
        [0, 0, 1, 0, 0, 2, 0, 0, 3],
        [0, 0, 0, 0, 1, 2, 0, 0, 0],
    ]
    for context in (6, 7):
        for selector in (16, 17):
            for rows in range(4):
                for columns in range(4):
                    case(selector, context, shape=(rows, columns), label='dimension-admission')
            case(selector, context, kind=9, label='vector-reduction-rejection')
            for native_error in range(16):
                case(selector, context, kind=15, identity=native_error,
                     label='F-current-reduction-rejection')
            for identity in range(16):
                for shape in ((1, 1), (1, 3), (2, 2), (3, 3)):
                    case(selector, context, identity=identity, shape=shape,
                         data=[decimal(x) for x in fixtures[6]], label='sixteen-physical-identities')
            case(selector, context, identity=12, shape=(1, 1),
                 updates=((0x80f9, bytes([context])),),
                 host_gap=None,  # Same retained input is now within the sufficient1x6/7 domain.
                 label='identity12-live-context-wide-boundary')
            for index, fixture in enumerate(fixtures):
                data = [decimal(x) for x in fixture]
                reached = case(selector, context, data=data, callback=True,
                    label='ordered-pivot-fixture-'+str(index))
                if reached is not None:
                    for cancel in range(1, reached+2):
                        case(selector, context, data=data, cancel=cancel, callback=True,
                             label='every-reached-cancellation-stage')
            for values in itertools.product((-1, 0, 1), repeat=4):
                data = [decimal(x) for x in (values[0], values[1], 97,
                    values[2], values[3], 98, 95, 96, 99)]
                case(selector, context, shape=(2, 2), data=data,
                     label='exhaustive-two-by-two')
            for record in exact + marked + errors + ordinary:
                for position in (0, 1, 3, 4, 8):
                    data = list(cells)
                    data[position] = record
                    case(selector, context, data=data, label='scalar-form-order')
            for record in (bytes([0x64])+bytes(9),
                           bytes([0x64])+bytes(7)+bytes((3, 1)),
                           bytes([0x24])+bytes(7)+bytes((3, 1))):
                for position in (0, 1, 4):
                    data = list(cells)
                    data[position] = record
                    case(selector, context, data=data, callback=True,
                         host_gap='Malformed zero-denominator fraction reaches unchecked rational arithmetic or comparison conversion',
                         label='unchecked-zero-denominator')
            for identity in (10, 11, 13, 14, 15):
                for record in exact[-2:]:
                    for position in (0, 1, 4):
                        data = list(cells)
                        data[position] = record
                        case(selector, context, identity=identity, data=data,
                             callback=identity==10 and record==exact[-1],
                             label='private-magnitude-candidate-copy-regression'
                                 if identity==10 and record==exact[-1] and position==0
                                 else 'surd-live-pool-physical-alias')
            for imaginary in (decimal(5), errors[0], errors[3]):
                case(selector, context, imaginary=imaginary,
                     other_imaginary=decimal(-3), label='retained-work-records')
            for poll, address, record in (
                (1, 0x829e+90*4+40, decimal(11)),
                (1, 0x8a00+10, decimal(5)),
                (1, 0x8a00+20, decimal(3)),
                (1, 0x8a00+30, decimal(5)),
                (1, 0x80e0+2*4, bytes((1, 1))),
            ):
                case(selector, context, callback=True,
                     mutations=((poll, address, record),), label='callback-live-RAM-mutation')
            case(selector, context, private_pair=True, label='separate-host-working-pair')
            case(selector, context, private_pair=True, callback=True,
                 mutations=((1,0x829e+90*4+40,decimal(11)),),
                 label='host-private-pair-bank-callback')
            case(selector, context, private_pair=True, callback=True,cancel=1,
                 label='host-private-pair-returned-callback-cancel')
            final_label='callback-final-F7-nominal-status'
            reached=case(selector,context,callback=True,imaginary=decimal(5),label=final_label)
            if reached is not None:
                case(selector,context,callback=True,imaginary=decimal(5),
                     mutations=((reached,0x8a00,errors[3]),),label=final_label)
            case(selector,context,callback=True,
                 mutations=((1,0x8406,bytes.fromhex('24000000000000000301')),),
                 host_gap='A callback installs a malformed fraction after prepared storage; unchecked comparison arithmetic remains a boundary',
                 label='callback-malformed-fraction-boundary')
            for address,reason in ((0x829e,'Physical working pair overlaps a physical bank'),
                                   (0x80e0,'Physical working pair overlaps dimension metadata'),
                                   (0x8c00,'Physical working pair overlaps native CPU frames')):
                case(selector,context,pair=address,host_gap=reason,
                     label='physical-working-pair-architecture-boundary')
            pending_label='callback-private-pending90-copy'
            pending=[decimal(x) for x in fixtures[0]]
            reached=case(selector,context,shape=(2,2),data=pending,callback=True,label=pending_label)
            if reached is not None:
                callers=(C.c_uint*256).in_dll(machine.lib,'reduce_poll_caller')
                check('native_pending_capture_then_product_poll',0x14a8e,callers[11],dict(label=pending_label,context=context,selector=selector))
                case(selector,context,shape=(2,2),data=pending,callback=True,
                     mutations=((12,0x8406+80,decimal(111)),),label=pending_label)
                states=((C.c_uint8*65536)*256).in_dll(machine.lib,'reduce_poll_memory')
                check('native_pending_inactive_mutation_visible_before_commit',decimal(111).hex(),
                      bytes(states[12][0x8456:0x8460]).hex(),dict(label=pending_label,context=context,selector=selector))
                check('native_pending90_commit_restores_cached_inactive_record',decimal(99).hex(),
                      bytes(machine.ram[0x8456:0x8460]).hex(),dict(label=pending_label,context=context,selector=selector))
            for position in (3,6):
                data=[decimal(0) if i in (0,3,6) else decimal(i+1) for i in range(9)]
                data[position]=exact[-1]
                case(selector,context,identity=10,data=data,callback=True,
                     host_gap='Ordered opposite-sign surd classifier source overlaps its live component pool',
                     label='ordered-classifier-pool-alias-boundary')
        backward_label='callback-backward-coefficient-reload'
        triangular=[decimal(x) for x in (1,2,3,0,1,4,0,0,1)]
        reached=case(17,context,data=triangular,callback=True,label=backward_label)
        if reached is not None:
            callers=(C.c_uint*256).in_dll(machine.lib,'reduce_poll_caller')
            check('native_first_backward_product_poll',0x14de8,callers[42],dict(label=backward_label,context=context))
            case(17,context,data=triangular,callback=True,cancel=44,
                 mutations=((43,0x8410,decimal(11)),),label=backward_label)
            converted=Number()
            native_value=Number.from_buffer_copy(bytes(machine.ram[0x841a:0x8424]))
            check('native_reloaded_coefficient_product_conversion',0,
                  implementation.fx_number_to_decimal(C.byref(converted),C.byref(native_value)),dict(label=backward_label,context=context))
            check('native_reloaded_coefficient_product_minus41',decimal(-41).hex(),bytes(converted).hex(),dict(label=backward_label,context=context))
            check('native_cancellation_retains_live_upper_coefficient',decimal(11).hex(),
                  bytes(machine.ram[0x8410:0x841a]).hex(),dict(label=backward_label,context=context))
        for selector in (21, 22):
            for identity in range(16):
                case(selector, context, identity=identity, kind=9,
                     shape=(1, 3), imaginary=decimal(5),
                     host_gap='Vector NOT only admits actual native contexts6/7'
                         if selector == 22 and identity == 12 else None,
                     label='wrapped-vector-leaf')
    regression=bytes.fromhex('8003010200050103010609000000000000000006800201010001000100018003010200050103010601000000000000000006090000000000000000060000000000000000000022a1a20000000000050103000000000000000006')
    case(17,7,identity=10,shape=(3,1),data=[regression[i:i+10] for i in range(0,90,10)],
         callback=True,label='private-magnitude-candidate-copy-regression')
    for context,cancel,payload in (
        (7,10,'21a300000000000003010990000000000000010103000000000000000006800301020005010301060700000000000000000180020101000100010001000000000000000000000100000000000000000109000000000000000006'),
        (6,40,'22a1a2000000000005010000000000000000000001000000000000000006800301020005010301060990000000000000010103000000000000000001010000000000000000010700000000000000000180030102000501030106')):
        raw=bytes.fromhex(payload)
        case(17,context,identity=10,data=[raw[i:i+10] for i in range(0,90,10)],
             cancel=cancel,callback=True,label='retained-seeded-classifier-pool-alias-boundary')
    for index in range(args.random_cases):
        pool = (integers, integers+exact, integers+marked+errors, ordinary)[index%4]
        identity = rng.choice(tuple(i for i in range(16) if i != 12))
        context=rng.choice((6,7))
        shape=(rng.randrange(1,4),rng.randrange(1,4))
        data=[rng.choice(pool) for _ in range(9)]
        cancel=rng.choice((0,0,1,2,5,10,20,40,60))
        classifier_alias=identity==10 and exact[-1] in data
        case(16+index%2, context, identity=identity,shape=shape,data=data,
             cancel=cancel,callback=classifier_alias,
             label='seeded-random')
    # Literal input-only supplemental corpus; every old generator runs unchanged above.
    for recipe in wide_cases:
        payload = bytes.fromhex(recipe['initial_payload90'])
        pair_record = bytes.fromhex(recipe['initial_pair40'])
        mutations = tuple((m['poll'],int(m['address'],16),bytes.fromhex(m['record']))
                          for m in recipe['mutations'])
        case(recipe['selector'],recipe['requested_context'],identity=recipe['identity'],
            shape=tuple(recipe['requested_shape']),kind=recipe['kind'],
            data=[payload[i:i+10] for i in range(0,90,10)],
            imaginary=pair_record[10:20],other_real=pair_record[20:30],other_imaginary=pair_record[30:40],
            cancel=recipe['cancel'],callback=recipe['callback'],mutations=mutations,
            pair=int(recipe['pair'],16),private_pair=recipe['private_pair'],
            updates=((int(recipe['pair'],16),pair_record),),
            label=recipe['label'],input_hash=recipe['initial_ram_sha256'],fixture_id=recipe['id'],
            host_gap='Malformed zero-denominator fraction reaches unchecked rational arithmetic or comparison conversion'
                if recipe['label']=='unchecked-zero-denominator' else None)
    for _ in actual_abi:
        counts['compiled_public_ABI'] += 1
    python_modules_end = local_python_inputs()
    end_hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                  for name in dependencies}
    changed = [name for name in dependencies if start_hashes[name] != end_hashes[name]]
    if python_modules_start != python_modules_end:
        changed.append('executed local Python import set')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    observation_file = build/('observations-'+args.optimization+'-'+stamp+'.json.gz')
    with gzip.open(observation_file,'wt',compresslevel=1) as stream:
        json.dump(dict(rows=observations,wide_final_states=wide_snapshots),stream)
    data = dict(checks=sum(counts.values()), groups=dict(counts), native_calls=native_calls,
        handled_native_calls=native_calls-len(gaps), explicit_boundaries=len(gaps),
        failures=len(failures), examples=failures, labels=dict(labels),
        architectural_gaps=gaps, optimization=args.optimization,
        random_cases=args.random_cases, random_seed='0x1477614786',
        diagnostic_labels=args.only_label,
        scope='Actual public rich address/private dispatch for prepared physical REF/RREF16/17 and wrapped vector21/22; owned public integration applies16562 cleanup once. No allocator, repeated storage stage, parser or UI.',
        comparison='Original16538 through16588; current20/other20, independent status, actual polling, temporary mask, dimensions32, all1440 physical bank bytes, and64KiB persistent RAM/MMIO plus callback snapshots. Excludes only8000..80DB scalar arithmetic arena and actually written native CPU-frame bytes.',
        planned_limits=['Zero dimensions retain native9. Positive literal stride3 coordinates require3*(rows-1)+columns<=9, a sufficient nine-record domain; identity12 column is actual80F9. Other native returning/nonreturning dimensions are not inferred from this guard.',
            'Physical work-record/bank or CPU-frame overlaps are separate named architectural boundaries.',
            'Malformed fractional arithmetic/conversion and opposite-sign physical classifier pool aliases are individually observed boundaries; preceding persistent RAM and callback states are compared at the reached original kernel entry.',
            'The callback return value controls the native timer answer; native CPU-frame/arena mutation is outside this comparison.'],
        input_hashes_start=start_hashes,input_hashes_end=end_hashes,source_changes=changed,
        python_modules_start=python_modules_start,python_modules_end=python_modules_end,
        wide_input_cases=len(wide_cases),wide_replayed_cases=len(wide_snapshots),compiled_ABI=actual_abi,
        observations=str(observation_file.relative_to(ROOT)) if observation_file.is_relative_to(ROOT) else str(observation_file),observations_sha256=hashlib.sha256(observation_file.read_bytes()).hexdigest(),
        compiled_artifact_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
        original_compiled_sha256=hashlib.sha256((oracle_dir/'nxu8-harness.so').read_bytes()).hexdigest(),
        generated_adapter_sha256=hashlib.sha256(ADAPTER.encode()).hexdigest(),
        generated_oracle_sha256=hashlib.sha256(ORACLE.encode()).hexdigest())
    (build/('pilot-'+args.optimization+'.json')).write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps({key: value for key, value in data.items()
                     if key not in ('examples','architectural_gaps','input_hashes_start','input_hashes_end','python_modules_start','python_modules_end')}, indent=2))
    if failures or changed:
        return 1
    if not args.no_report:
        report = write_report('analysis/c-verification/eval_rich_reduce.json', data,
            dependencies,
            'tools/test_eval_rich_reduce_c.py')
        print(json.dumps(dict(status=report['status'], pins=len(report['tested_inputs_sha256']))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
