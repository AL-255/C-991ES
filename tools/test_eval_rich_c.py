#!/usr/bin/env python3
"""Original16538 post-storage matrix/vector dispatch versus high-level C.

The test-only observer executes every original instruction. It supplies the
5564 timer response and stops at16588 after numerical context cleanup. No
storage allocator/stage, parser, lifted instructions or ROM executor is linked
into the production C implementation. Full physical storage remains visible.
"""
import argparse
import base64
import ctypes as C
import hashlib
import json
import random
import subprocess
import zlib

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
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


SOURCES = ['parse/fx_eval_rich.c', 'parse/fx_eval_rich_unary.c',
           'parse/fx_eval_rich_reduce.c',
           'parse/fx_eval_surd_workspace.c',
           'platform/fx_platform.c', 'platform/fx_result_classify.c',
           'linalg/fx_linalg.c',
           'complex/fx_complex_dispatch.c', 'complex/fx_complex.c',
           'complex/fx_complex_angle.c', 'complex/fx_complex_round.c',
           'numeric/fx_numeric.c', 'numeric/fx_transcend.c', 'numeric/fx_power.c',
           'numeric/fx_root.c', 'numeric/fx_combinatorics.c', 'numeric/fx_logbase.c',
           'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c',
           'trig/fx_trig_hyperbolic.c', 'numeric/fx_raw_decimal_parts.c',
           'numeric/fx_raw_decimal_divide.c', 'numeric/fx_raw_decimal_multiply_add.c',
           'numeric/fx_raw_fraction_convert.c', 'numeric/fx_raw_decimal_exp.c']

ORACLE = r'''
#include "harness.c"
unsigned rich_polls, rich_minimum_sp, rich_target;
unsigned rich_frame_operand_reads, rich_first_frame_source, rich_first_frame_pc;
unsigned rich_observe_callbacks;
unsigned rich_callback_mutate_address, rich_callback_mutate_poll;
uint8_t rich_callback_mutate_bytes[10];
uint8_t rich_poll_memory[256][65536], rich_poll_frame_writes[256][65536];
int rich_scalar_run(unsigned entry, unsigned current, unsigned other) {
    harness_set_sp(0x8dee); harness_set_pc(entry); harness_set_lr(0x2fffe);
    harness_set_reg(0,current&255); harness_set_reg(1,current>>8);
    harness_set_reg(2,other&255); harness_set_reg(3,other>>8);
    return harness_run(3000000,0x2fffe,false);
}
int rich_run(unsigned selector, unsigned pair, unsigned cancel) {
    harness_set_sp(0x8dee); harness_set_pc(0x16538); harness_set_lr(0x2fffe);
    harness_set_reg(1, selector); harness_set_reg(12, pair & 255);
    harness_set_reg(13, pair >> 8);
    rich_polls=rich_target=0; rich_minimum_sp=0x8dee;
    rich_frame_operand_reads=rich_first_frame_source=rich_first_frame_pc=0;
    for (uint64_t n=0; n<20000000; ++n) {
        uint32_t pc=harness_get_pc(); unsigned sp=harness_get_sp();
        if (sp<rich_minimum_sp) rich_minimum_sp=sp;
        if (pc==0x16588) return100;
        if (pc==0x1655c)
            rich_target=0x10000u | harness_get_reg(4) | (unsigned)harness_get_reg(5)<<8;
        /* Observe the actual bank source at norm-copy / absolute entry.
         * A source entering already-written CPU locals is an architectural
         * boundary, independently of the C helper's supported dimensions. */
        if (pc==0x14710 || pc==0x14118) {
            unsigned reg=pc==0x14710 ? 4 : 0;
            unsigned source=harness_get_reg(reg) | (unsigned)harness_get_reg(reg+1)<<8;
            for (unsigned j=0; j<10; ++j) {
                unsigned a=source+j;
                if (a>=rich_minimum_sp && a<0x8df0 && ram_write_counts[a]) {
                    if (!rich_frame_operand_reads) {
                        rich_first_frame_source=source; rich_first_frame_pc=pc;
                    }
                    ++rich_frame_operand_reads; break;
                }
            }
        }
        if (pc==0x5564) {
            ++rich_polls;
            if (rich_observe_callbacks && rich_polls<=256) {
                unsigned index=rich_polls-1;
                memcpy(rich_poll_memory[index], ram, 65536);
                memset(rich_poll_frame_writes[index], 0, 65536);
                for (unsigned a=rich_minimum_sp; a<0x8df0; ++a)
                    rich_poll_frame_writes[index][a]=(uint8_t)(ram_write_counts[a]!=0);
            }
            if (rich_callback_mutate_address && rich_polls==rich_callback_mutate_poll)
                memcpy(ram+rich_callback_mutate_address,rich_callback_mutate_bytes,10);
            ram[0x8e00]=(uint8_t)(cancel && rich_polls==cancel);
        }
        int status=harness_run(1, 0x2fffe, false);
        if (status!=103) return status;
    }
    return103;
}
'''.replace('return100', 'return 100').replace('return103', 'return 103')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=4000)
    parser.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    parser.add_argument('--no-report', action='store_true')
    options = parser.parse_args()
    build = ROOT / 'analysis/build/eval-rich'
    build.mkdir(parents=True, exist_ok=True)
    library = build / ('rich-' + options.optimization + '.so')
    subprocess.run(['gcc', '-std=c99', '-' + options.optimization, '-Wall', '-Wextra',
                    '-Werror', '-pedantic', '-shared', '-fPIC',
                    *[str(ROOT / 'csrc' / p) for p in SOURCES], '-o', str(library)], check=True)
    implementation = C.CDLL(str(library))
    implementation.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    implementation.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    implementation.fx_surd_pack.argtypes = [C.POINTER(Number), C.POINTER(Number)]
    implementation.fx_eval_rich_dispatch_address.argtypes = [C.POINTER(Result), C.POINTER(Storage),
        C.c_uint16, C.c_uint8, C.POINTER(Context)]
    implementation.fx_eval_surd_workspace_binary.argtypes = [C.POINTER(Number),
        C.POINTER(C.c_uint8), C.POINTER(Number), C.POINTER(Number),
        C.c_uint16, C.c_uint16, C.c_int]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    oracle_dir = build / ('oracle-' + options.optimization)
    oracle_dir.mkdir(exist_ok=True)
    helper = oracle_dir / 'rich-observer.c'
    helper.write_text(ORACLE)
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    '-I', str(ROOT / 'tools/nxu8'), str(helper),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
                    '-o', str(oracle_dir / 'nxu8-harness.so')], check=True)
    m = Machine(rom, oracle_dir)
    m.lib.rich_run.argtypes = [C.c_uint, C.c_uint, C.c_uint]
    m.lib.rich_scalar_run.argtypes = [C.c_uint, C.c_uint, C.c_uint]
    rom_buffer = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
    rng = random.Random(0x16538291e)
    counts, failures, boundaries = {}, [], []
    native_calls = 0

    def decimal(value):
        n = Number()
        assert implementation.fx_decimal_parse(C.byref(n), str(value).encode()) == 0
        return bytes(n)

    def rational(numerator, denominator):
        n = Number()
        assert implementation.fx_rational_encode(C.byref(n),
            C.byref(Rational(numerator, denominator, 0))) == 0
        return bytes(n)

    def surd(integer):
        n = Number()
        components = (Number * 6)(*[Number.from_buffer_copy(decimal(x))
                                   for x in (1, integer, 1, 0, 1, 1)])
        assert implementation.fx_surd_pack(C.byref(n), components) == 0
        return bytes(n)

    zero = bytes(10)
    scalar_values = [decimal(x) for x in (0, 1, -1, 2, -2, '1.23456789012345', '1e-99', '1e99')]
    scalar_values += [rational(1, 3), rational(-2, 7), surd(2), surd(3)]
    cells = [decimal(i + 1) for i in range(9)]

    def check(group, expected, actual, detail):
        counts[group] = counts.get(group, 0) + 1
        if expected != actual:
            row = dict(group=group, expected=expected, actual=actual, **detail)
            failures.append(row)
            if len(failures) <= 15:
                print(json.dumps(row), flush=True)

    def case(selector, context=193, identity=4, right_identity=5, kind=6,
             right_kind=None, shape=(2, 2), right_shape=None, left_cells=None,
             right_cells=None, scalar=None, imaginary=zero, other_imaginary=None,
             cancel=0, pair=0x9300, label='', updates=(), host_gap=None,
             callback=False, callback_mutation=None):
        nonlocal native_calls
        memory = bytearray(65536)
        # Every inactive physical bank slot is initialized and compared.
        for slot in range(16):
            memory[0x80e0+slot*2:0x80e2+slot*2] = bytes((0, 0))
            payload = 0x829e + 90 * slot
            memory[payload:payload+90] = b''.join(decimal(9 * slot + j + 1) for j in range(9))
        memory[0x80e0+2*identity:0x80e2+2*identity] = bytes(shape)
        memory[0x80e0+2*right_identity:0x80e2+2*right_identity] = bytes(right_shape or shape)
        memory[0x829e+90*identity:0x82f8+90*identity] = b''.join(left_cells or cells)
        memory[0x829e+90*right_identity:0x82f8+90*right_identity] = b''.join(right_cells or cells)
        current = bytes([kind * 16 + identity]) + bytes(9) + imaginary
        other = (scalar if selector in (11, 12) else
                 bytes([(right_kind if right_kind is not None else kind) * 16 + right_identity]) + bytes(9))
        other += decimal(-7) if other_imaginary is None else other_imaginary
        memory[pair:pair+40] = current + other
        memory[0x80f9] = context
        memory[0x8106] = 1
        memory[0x8125] = 0x98
        for address, data in updates:
            memory[address:address+len(data)] = data
        initial = bytes(memory)
        context = memory[0x80f9]
        exact = bool(context & 0x40 and memory[0x8106] and memory[0x810c] != 1 and
                     not (memory[0x80fc] & 0x40) and memory[0x80f5] != 0xed and
                     not (memory[0x8124] & 1))
        numerical = Context(context, NumericContext(exact, memory[0x8102],
                                                    memory[0x8103], 0 if callback else cancel))
        callback_states = []
        callback_userdata_values = []
        userdata = C.c_uint32(0x16538291)
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p)
        @callback_type
        def sample_cancel(_userdata):
            callback_states.append(bytes(memory))
            callback_userdata_values.append(C.cast(_userdata,C.POINTER(C.c_uint32))[0])
            if callback_mutation is not None and len(callback_states) == callback_mutation[2]:
                address, record, _poll = callback_mutation
                memory[address:address+10] = record
            return bool(cancel and len(callback_states) == cancel)
        if callback:
            numerical.cancelled = C.cast(sample_cancel, C.c_void_p).value
            numerical.userdata = C.cast(C.byref(userdata),C.c_void_p).value
        buffer = (C.c_uint8 * 65536).from_buffer(memory)
        storage = Storage(buffer, 65536, rom_buffer, len(rom))
        out = Result()
        C.memset(C.byref(out), 0xad, C.sizeof(out))
        m.reset(); C.memmove(C.addressof(m.ram), initial, 65536)
        C.c_uint.in_dll(m.lib, 'rich_observe_callbacks').value = int(callback)
        C.c_uint.in_dll(m.lib, 'rich_callback_mutate_address').value = (
            callback_mutation[0] if callback_mutation is not None else 0)
        C.c_uint.in_dll(m.lib, 'rich_callback_mutate_poll').value = (
            callback_mutation[2] if callback_mutation is not None else 0)
        if callback_mutation is not None:
            C.memmove((C.c_uint8*10).in_dll(m.lib,'rich_callback_mutate_bytes'),
                      callback_mutation[1],10)
        stopped = m.lib.rich_run(selector, pair, cancel); native_calls += 1
        detail = dict(label=label, selector=selector, context=context, identity=identity,
                      right_identity=right_identity, shape=shape, right_shape=right_shape,
                      kind=kind, right_kind=right_kind, cancel=cancel, pair=f'{pair:04x}')
        detail['initial_pair40'] = initial[pair:pair+40].hex()
        detail['initial_left90'] = initial[0x829e+90*identity:0x82f8+90*identity].hex()
        detail['initial_right90'] = initial[0x829e+90*right_identity:0x82f8+90*right_identity].hex()
        minimum_sp = C.c_uint.in_dll(m.lib, 'rich_minimum_sp').value
        target = C.c_uint.in_dll(m.lib, 'rich_target').value
        expected_target = 0x10000 | int.from_bytes(
            rom[0x291e+((selector*2)&255):0x2920+((selector*2)&255)], 'little')
        check('static_table_target', expected_target, target, detail)
        check('no_repeated_storage_stage', 0, m.counts[0x163f0//2], detail)
        native = bytearray(m.ram)
        host = implementation.fx_eval_rich_dispatch_address(C.byref(out), C.byref(storage),
            pair, selector, C.byref(numerical))
        if stopped != 100:
            boundaries.append(dict(native_stop=stopped, native_pc=f'{m.lib.harness_get_pc():05x}',
                                   minimum_sp=f'{minimum_sp:04x}', host_status=host, **detail))
            check('explicit_native_nonreturn', -3, host, detail)
            return
        if host_gap is not None:
            if host_gap == 'The bank source reads live native CPU descriptor/frame bytes':
                check('native_CPU_operand_read_witness', True,
                      C.c_uint.in_dll(m.lib, 'rich_frame_operand_reads').value > 0, detail)
            boundaries.append(dict(native_stop=stopped, native_pc=f'{m.lib.harness_get_pc():05x}',
                                   minimum_sp=f'{minimum_sp:04x}', host_status=host,
                                   native_current20=bytes(native[pair:pair+20]).hex(),
                                   native_status=m.reg(0),
                                   native_RAM_sha256=hashlib.sha256(native).hexdigest(),
                                   native_frame_operand_reads=C.c_uint.in_dll(m.lib, 'rich_frame_operand_reads').value,
                                   native_first_frame_source=f"{C.c_uint.in_dll(m.lib, 'rich_first_frame_source').value:04x}",
                                   native_first_frame_pc=f"{C.c_uint.in_dll(m.lib, 'rich_first_frame_pc').value:05x}",
                                   domain_gap=host_gap, **detail))
            check('explicit_returned_architecture_gap', -3, host, detail)
            return
        check('host_status', 0, host, detail)
        if host != 0:
            return
        if callback:
            native_polls = C.c_uint.in_dll(m.lib, 'rich_polls').value
            check('actual_cancellation_callback_count', native_polls, len(callback_states), detail)
            check('callback_userdata', [0x16538291]*native_polls, callback_userdata_values, detail)
            native_states = ((C.c_uint8 * 65536) * 256).in_dll(m.lib, 'rich_poll_memory')
            frame_writes = ((C.c_uint8 * 65536) * 256).in_dll(m.lib, 'rich_poll_frame_writes')
            for index, actual in enumerate(callback_states):
                expected = bytearray(native_states[index])
                expected[0x8000:0x80dc] = actual[0x8000:0x80dc]
                for address, written in enumerate(frame_writes[index]):
                    if written:
                        expected[address] = actual[address]
                differences = [dict(address=f'{address:04x}', native=expected[address],
                                    c=actual[address]) for address in range(65536)
                               if expected[address] != actual[address]]
                check('callback_full_RAM_before_answer', hashlib.sha256(expected).hexdigest(),
                      hashlib.sha256(actual).hexdigest(),
                      dict(poll=index+1, differences=differences[:20], **detail))
        check('native_status', m.reg(0), out.firmware_status, detail)
        check('current20', bytes(native[pair:pair+20]).hex(), bytes(out.value).hex(), detail)
        check('other20', bytes(native[pair+20:pair+40]).hex(), bytes(out.other).hex(), detail)
        check('cancellation_checks', C.c_uint.in_dll(m.lib, 'rich_polls').value,
              out.cancellation_checks, detail)
        # The arithmetic register arena is a separate value-kernel interface.
        # All bank dimensions/payload, including8640..87CF, and all MMIO remain
        # visible. CPU frame exclusions require actual native write witnesses.
        native[0x8000:0x80dc] = memory[0x8000:0x80dc]
        for address in range(minimum_sp, 0x8df0):
            if m.ram_writes[address]:
                native[address] = memory[address]
        if native != memory:
            differences = [dict(address=f'{a:04x}', native=native[a], c=memory[a])
                           for a in range(65536) if native[a] != memory[a]]
            check('remaining_full_RAM', [], differences[:20],
                  dict(differences=len(differences), **detail))
        else:
            check('remaining_full_RAM', True, True, detail)

    for context in (193, 196, 2, 6, 7):
        for selector in range(9, 16):
            case(selector, context, kind=9 if selector in (13, 14) else 6,
                 shape=(1, 3) if selector in (13, 14) else (2, 2),
                 scalar=decimal(2), label='canonical-default')
            for imaginary in (decimal(1), bytes([0xf0])+bytes(9), bytes([0xf7])+bytes(9)):
                case(selector, context, kind=9 if selector in (13, 14) else 6,
                     shape=(1, 3) if selector in (13, 14) else (2, 2),
                     scalar=decimal(2), imaginary=imaginary, label='retained-imaginary')
            for identity in range(16):
                case(selector, context, identity=identity,
                     kind=9 if selector in (13, 14) else 6,
                     scalar=decimal(2), cancel=1 if selector in (11, 12, 15) else 0,
                     label='physical-sixteen-slot')
            for status in range(16):
                case(selector, context, identity=status, kind=15,
                     scalar=decimal(2), label='F-current-leaf-rejection')
            for shape in ((0, 0), (0, 1), (1, 0), (1, 1), (3, 3)):
                case(selector, context, kind=9 if selector in (13, 14) else 6,
                     shape=shape, scalar=decimal(2), label='shape-boundary')
    for selector in range(9, 16):
        for form, values in [('rational', [rational(1, 3), rational(2, 7)]),
                             ('surd', [surd(2), surd(3)])]:
            case(selector, kind=9 if selector in (13, 14) else 6,
                 shape=(1, 3) if selector in (13, 14) else (2, 2),
                 scalar=decimal(2), left_cells=[values[0]]+cells[1:],
                 right_cells=[values[1]]+cells[1:], label=form+'-workspace')
        for native_error in (0, 1, 3, 7, 15):
            for position in (0, 1, 4):
                error_cells = list(cells)
                error_cells[position] = bytes([0xf0 | native_error]) + bytes(9)
                case(selector, kind=9 if selector in (13, 14) else 6,
                     shape=(1, 3) if selector in (13, 14) else (2, 2),
                     scalar=decimal(2), left_cells=error_cells,
                     label='partial-cell-error')
        for ordinary in (decimal('1.23456789012345'), rational(1, 3)):
            marked = bytes([ordinary[0] | 0x40]) + ordinary[1:]
            case(selector, kind=9 if selector in (13, 14) else 6,
                 shape=(1, 3) if selector in (13, 14) else (2, 2),
                 scalar=decimal(2), left_cells=[marked]+cells[1:],
                 right_cells=[ordinary]+cells[1:], label='metadata-conversion-order')
        for context in (193, 196, 2, 6, 7):
            for native_error in (0, 3):
                error = bytes([0xf0 | native_error]) + bytes(9)
                for reverse in (False, True):
                    first, second = (error, surd(2)) if reverse else (surd(2), error)
                    case(selector, context,
                         kind=9 if selector in (13, 14) else 6,
                         shape=(1, 3) if selector in (13, 14) else (2, 2),
                         scalar=second, left_cells=[first]+cells[1:],
                         right_cells=[second]+cells[1:],
                         label='surd-error-ordered-workspace')
    for context in (193, 196, 2, 6, 7):
        for selector in range(9):
            for kind in (6, 9, 15):
                case(selector, context, kind=kind, right_kind=6,
                     shape=(1, 3) if selector == 0 else (2, 2),
                     host_gap='C4 round overwrites its native10-byte saved frame with20-byte copy'
                         if selector == 2 and context == 196 and kind in (6, 9) else None,
                     label='unary-admission')
            for status in range(16):
                case(selector, context, identity=status, kind=15,
                     label='unary-F-status')
            for imaginary in (decimal(1), bytes([0xf0])+bytes(9),
                              bytes([0xf7])+bytes(9)):
                case(selector, context, kind=9 if selector == 0 else 6,
                     shape=(1, 3) if selector == 0 else (2, 2),
                     host_gap='C4 round overwrites its native10-byte saved frame with20-byte copy'
                         if selector == 2 and context == 196 else None,
                     imaginary=imaginary, label='unary-retained-imaginary')
            for identity in range(16):
                case(selector, context, identity=identity,
                     kind=9 if selector == 0 else 6,
                     shape=(1, 2) if selector == 0 else (2, 2),
                     cancel=1 if selector in (1, 3, 5, 6, 7, 8) else 0,
                     host_gap='C4 round overwrites its native10-byte saved frame with20-byte copy'
                         if selector == 2 and context == 196 else
                         'The bank source reads live native CPU descriptor/frame bytes'
                         if identity == 12 and selector in (0, 1) and context in (193, 196) else None,
                     label='unary-sixteen-physical-slots')
        for selector in (162, 163, 164):
            for kind in (6, 9, 15):
                for identity in range(16):
                    case(selector, context, identity=identity, kind=kind,
                         label='wrapped-unary-raw-metadata')
    for context in (193, 196, 2, 6, 7):
        for inner in (1, 2, 3):
            case(15, context, shape=(4, inner), right_shape=(inner, 1),
                 label='matrix-fourth-row-numeric-local-alias')
        for inner in (1, 2):
            case(15, context, shape=(4, inner), right_shape=(inner, 2),
                 host_gap='Matrix output index10 overwrites native CPU pointer/loop descriptor',
                 label='matrix-native-descriptor-boundary')
        for selector in (11, 12):
            case(selector, context, identity=0, shape=(1, 2),
                 left_cells=[decimal(2), decimal(8)]+cells[2:],
                 scalar=decimal(2), other_imaginary=decimal(8), pair=0x828a,
                 label='live-factor-alias-first-payload-cell')
            case(selector, context, identity=0, shape=(1, 2),
                 scalar=decimal(2), pair=0x82a8,
                 label='current-record-alias-second-payload-cell')
    for context in (193, 196):
        case(14, context, identity=12, kind=9, shape=(1, context),
             imaginary=decimal(1), label='cross-retains-context-before-dimension-alias')
        case(15, context, identity=12, shape=(1, context), right_shape=(context, 1),
             cancel=1, imaginary=decimal(1),
             label='matrix-retains-context-before-dimension-alias')
    for context in (193, 196, 2, 6, 7):
        for selector in (3, 5, 6, 7, 8, 11, 12, 15):
            for cancel in (0, 1, 2, 4, 8, 12, 20):
                case(selector, context, scalar=decimal(2), cancel=cancel,
                     callback=True, label='actual-cancellation-callback')
        for selector in (5, 11, 12):
            for mutation in ((0x9314,decimal(3),1),
                             (0x829e+90*4+10,decimal(11),1),
                             (0x930a,decimal(5),1),
                             (0x931e,decimal(5),1),
                             (0x9300,bytes([0xf7])+bytes(9),4)):
                case(selector, context, scalar=decimal(2), callback=True,
                     callback_mutation=mutation,
                     label='callback-mutation-before-next-live-operand')
        for record in ('64000000000000000000', '24000000000000000000',
                       '20000000000000000000', '64000000000000000301',
                       '24000000000000000301'):
            case(6, context, callback=True,
                 callback_mutation=(0x829e+90*4,bytes.fromhex(record),6),
                 label='inverse-callback-malformed-fraction-numerator')
    for selector in (9, 10, 11, 12, 13, 14, 15):
        for identity in (10, 11, 13, 14, 15):
            for right_identity in (4, 11, 13):
                case(selector, identity=identity, right_identity=right_identity,
                     kind=9 if selector in (13, 14) else 6,
                     shape=(1, 3) if selector in (13, 14) else (2, 2),
                     scalar=decimal(2), left_cells=[surd(2)]+cells[1:],
                     right_cells=[surd(3)]+cells[1:],
                     cancel=1 if selector in (11, 12, 15) else 0,
                     label='surd-physical-pool-slot-alias')
    for _ in range(options.random_cases):
        selector = rng.randrange(9, 16)
        shape = (1, rng.choice((2, 3))) if selector in (13, 14) else (rng.randrange(1, 4), rng.randrange(1, 4))
        right_shape = (shape[1], rng.randrange(1, 4)) if selector == 15 else shape
        case(selector, rng.choice((193, 196, 2, 6, 7)), identity=rng.randrange(9),
             right_identity=rng.randrange(9), kind=9 if selector in (13, 14) else 6,
             shape=shape, right_shape=right_shape, scalar=rng.choice(scalar_values),
             left_cells=[rng.choice(scalar_values) for _ in range(9)],
             right_cells=[rng.choice(scalar_values) for _ in range(9)],
             cancel=rng.choice((0, 0, 1, 2, 5)), label='random-canonical')
    dispatch_native_calls = native_calls
    workspace_fixture = 'analysis/native-fixtures/eval-rich/surd-workspace/inputs.json'
    workspace_inputs = json.loads((ROOT / workspace_fixture).read_text())
    for row in workspace_inputs['rows']:
        initial = zlib.decompress(base64.b64decode(row['initial_ram_zlib_base64']))
        assert len(initial) == 65536 and hashlib.sha256(initial).hexdigest() == row['initial_ram_sha256']
        memory = bytearray(initial)
        current, other = row['current'], row['other']
        left = Number.from_buffer_copy(initial[current:current+10])
        right = Number.from_buffer_copy(initial[other:other+10])
        output = Number()
        m.reset(); C.memmove(C.addressof(m.ram), initial, 65536)
        stopped = m.lib.rich_scalar_run(row['entry'], current, other)
        native_calls += 1
        detail = dict(label=row['name'], entry=f"{row['entry']:05x}",
                      current=f'{current:04x}', other=f'{other:04x}')
        check('workspace_original_return', 100, stopped, detail)
        check('workspace_original_fixture_record', row['original_record'],
              bytes(m.ram[current:current+10]).hex(), detail)
        check('workspace_original_fixture_status', row['original_status'], m.reg(0), detail)
        check('workspace_original_fixture_payload', row['original_payload_hex'],
              bytes(m.ram[0x829e:0x883e]).hex(), detail)
        operation = {'ADD':0,'SUBTRACT':1,'MULTIPLY':2,'DIVIDE':3}[row['name'].split('_')[0]]
        buffer = (C.c_uint8 * 65536).from_buffer(memory)
        host = implementation.fx_eval_surd_workspace_binary(C.byref(output),buffer,
            C.byref(left),C.byref(right),current,other,operation)
        check('workspace_host_status', 0, host, detail)
        if host != 0:
            continue
        memory[current:current+10] = bytes(output)
        check('workspace_record', bytes(m.ram[current:current+10]).hex(), bytes(output).hex(), detail)
        check('workspace_payload1440', bytes(m.ram[0x829e:0x883e]).hex(),
              memory[0x829e:0x883e].hex(), detail)
    data = dict(checks=sum(counts.values()), groups=counts, native_calls=native_calls,
                dispatch_native_calls=dispatch_native_calls,
                surd_workspace_native_calls=native_calls-dispatch_native_calls,
                failures=len(failures), examples=failures,
                native_architectural_boundaries=boundaries,
                optimization=options.optimization,
                comparison='Original16538 through16588: full current20/other20, independent status, poll count, full16-slot dimensions/payload and remaining64KiB RAM/MMIO. Only8000..80DB arithmetic value arena and actually written native CPU-frame bytes are excluded;8640..87CF bank aliases remain compared.',
                direct_workspace_comparison='Additional original scalar arithmetic leaves: all172 immutable inputs freshly replayed; compare10-byte scalar record and all1440 physical payload bytes. Full64KiB parity is not claimed for these direct controls.',
                scope='Already staged rich numeric leaves; no allocation, repeated stage, parser or evaluator orchestration.')
    (build / ('pilot-' + options.optimization + '.json')).write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps({k: v for k, v in data.items() if k not in ('examples', 'native_architectural_boundaries')}, indent=2))
    if failures:
        raise SystemExit(1)
    sources = implementation_inputs(ROOT, ['csrc/'+p for p in SOURCES])
    if not options.no_report:
        report_path = 'analysis/c-verification/eval_rich.json' if options.optimization == 'O2' else 'analysis/c-verification/eval_rich_o3.json'
        report = write_report(report_path, data,
            sources + [workspace_fixture, 'tools/c_build_inputs.py', 'tools/c_verification.py'],
            'tools/test_eval_rich_c.py')
        print(json.dumps(dict(status=report['status'], pins=len(report['tested_inputs_sha256']))))


if __name__ == '__main__':
    main()
