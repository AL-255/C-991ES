#!/usr/bin/env python3
"""Prepared004F26 TABLE differential test with an explicit native171EA seam.

The implementation never executes firmware. This verifier runs the original
TABLE transaction, records its actual mode88 evaluator and between-row device
boundaries, then supplies those boundary observations to the handwritten C
kernel. Whole persistent RAM is compared, including every physical rich slot;
only the original measured CPU-frame region and arithmetic-register arena are
outside the named kernel API. All original nonreturns and host gaps are kept.
Diagnostics live under analysis/build/table. Passing runs publish canonical
metadata unless --no-report is requested; O3 also pins the preceding O2 run.
"""
import argparse
import collections
import ctypes as C
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import random
import subprocess

from c_build_inputs import implementation_inputs
from c_verification import write_report
from nxu8.machine import Machine

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = r'''
/* Original-ROM TABLE observer; no arithmetic/result substitutions. */
#include "@HARNESS@"
#define CAPACITY 64
uint64_t table_steps, table_callbacks, table_polls, table_commits;
uint64_t table_cancel_at;
unsigned table_minimum_sp;
uint8_t table_cb_before[CAPACITY][65536], table_cb_after[CAPACITY][65536];
uint8_t table_poll_before[CAPACITY][65536], table_poll_after[CAPACITY][65536];
uint8_t table_cb_output[CAPACITY][10], table_cb_status[CAPACITY];
uint8_t table_cb_mode[CAPACITY], table_cb_continuation[CAPACITY];
uint8_t table_cb_complete[CAPACITY], table_poll_complete[CAPACITY];
uint16_t table_cb_begin[CAPACITY], table_cb_end[CAPACITY];
uint8_t table_poll_status[CAPACITY];
uint8_t table_commit_column[CAPACITY * 2], table_commit_row[CAPACITY * 2];
uint8_t table_commit_value[CAPACITY * 2][10];
int table_callback_active, table_poll_active;
uint64_t table_mutation_callback;
unsigned table_mutation_count;
uint16_t table_mutation_address[32];
uint8_t table_mutation_value[32];
void table_observer_reset(uint64_t cancel_at) {
    table_steps = table_callbacks = table_polls = table_commits = 0;
    table_minimum_sp = SP; table_cancel_at = cancel_at;
    table_callback_active = table_poll_active = 0;
    table_mutation_callback = 0; table_mutation_count = 0;
}
/* Explicit prepared callback effects, applied at its actual native return
 * boundary. Original instructions/output/status are never replaced. */
void table_observer_mutation(uint64_t callback, const uint16_t *addresses,
                             const uint8_t *values, unsigned count) {
    table_mutation_callback = callback; table_mutation_count = count;
    for (unsigned i = 0; i < count && i < 32; ++i) {
        table_mutation_address[i] = addresses[i]; table_mutation_value[i] = values[i];
    }
}
int table_observer_run(uint64_t limit, uint32_t stop) {
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t pc = harness_get_pc();
        if (SP < table_minimum_sp) table_minimum_sp = SP;
        if (pc == stop) return 100;
        if (pc == 0x171ea) {
            uint64_t j = table_callbacks++;
            if (j >= CAPACITY) return 104;
            memcpy(table_cb_before[j], ram, 65536);
            table_cb_begin[j] = GR.ers[7];
            table_cb_mode[j] = ram[0x80f9];
            table_cb_continuation[j] = GR.rs[6];
            table_cb_complete[j] = 0;
            table_callback_active = 1;
        }
        if (pc == 0x4fe6 && table_callback_active) {
            uint64_t j = table_callbacks - 1;
            if (table_mutation_callback == j + 1)
                for (unsigned k = 0; k < table_mutation_count && k < 32; ++k)
                    ram[table_mutation_address[k]] = table_mutation_value[k];
            memcpy(table_cb_after[j], ram, 65536);
            memcpy(table_cb_output[j], ram + GR.ers[6], 10);
            table_cb_status[j] = GR.rs[0]; table_cb_end[j] = GR.ers[7];
            table_cb_complete[j] = 1;
            table_callback_active = 0;
        }
        if (pc == 0x5550 && LR == 0x5024) {
            uint64_t j = table_polls++;
            if (j >= CAPACITY) return 104;
            memcpy(table_poll_before[j], ram, 65536); table_poll_active = 1;
            table_poll_complete[j] = 0;
        }
        if (pc == 0x5564) {
            ram[0x8e00] = table_poll_active && table_cancel_at &&
                table_polls == table_cancel_at ? 2 : 0;
        }
        if (pc == 0x5024 && table_poll_active) {
            uint64_t j = table_polls - 1;
            memcpy(table_poll_after[j], ram, 65536);
            table_poll_status[j] = GR.rs[0]; table_poll_active = 0;
            table_poll_complete[j] = 1;
        }
        if (pc == 0x1d66c) {
            uint64_t j = table_commits++;
            if (j >= CAPACITY * 2) return 104;
            table_commit_column[j] = GR.rs[0]; table_commit_row[j] = GR.rs[1];
            memcpy(table_commit_value[j], ram + GR.ers[1], 10);
        }
        int status = harness_run(1, stop, false);
        ++table_steps;
        if (status != 103) return status;
    }
    return 103;
}
'''


class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]


class Rational(C.Structure):
    _fields_ = [('numerator', C.c_int64), ('denominator', C.c_uint64), ('flags', C.c_uint8)]


Evaluate = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(C.c_uint8),
    C.c_uint8, C.c_uint8, C.POINTER(C.c_uint16), C.POINTER(Number))
Poll = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(C.c_uint8))


class Control(C.Structure):
    _fields_ = [('evaluate', Evaluate), ('poll', Poll), ('userdata', C.c_void_p)]


class Result(C.Structure):
    _fields_ = [('source', C.c_uint16), ('planned_rows', C.c_uint8),
        ('evaluated_rows', C.c_uint8), ('committed_rows', C.c_uint8), ('polls', C.c_uint32)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decimal(value, marked=False):
    d = Decimal(str(value)); negative = d < 0; d = abs(d)
    if not d:
        return bytes([0x40 if marked else 0]) + bytes(9)
    exponent = d.adjusted()
    digits = ''.join(str(x) for x in d.as_tuple().digits).ljust(15, '0')[:15]
    tag = (6 if negative else 1) if exponent >= 0 else (5 if negative else 0)
    return bytes([int(digits[0]) + (0x40 if marked else 0),
        *[int(digits[i:i+2], 16) for i in range(1, 15, 2)],
        int(f'{exponent if exponent >= 0 else exponent + 100:02d}', 16), tag])


def seed(expression, start, end, step, functions=0, phase=0, pointer=0x9900):
    memory = bytearray(65536)
    for address, value in ((0x80f9, 0x88), (0x80fa, 0), (0x80fc, 6),
        (0x80fd, 4), (0x80f5, 240), (0x8106, 1), (0x8121, 1),
        (0x8105, 4), (0x8104, 1), (0x810e, functions), (0x8138, phase),
        (0x80de, 5), (0x80df, 7), (0x8125, 0xa5),
        (0x811c, 3), (0x811d, 2), (0x811e, 3)):
        memory[address] = value
    for address in (0x812c, pointer):
        memory[address] = 0
        memory[(address + 1) & 65535] = 0x82
    memory[0x8200:0x8201+len(expression)] = expression + b'\0'
    for address, value in ((0x829e, start), (0x82a8, end), (0x82b2, step)):
        memory[address:address+10] = value if isinstance(value, bytes) else decimal(value)
    memory[0x82ee:0x8546] = bytes([0xa7]) * 600
    memory[0x8276:0x8280] = decimal(99)
    return bytes(memory)


class Native:
    def __init__(self, build, rom):
        self.machine = Machine(rom, build/'base-oracle')
        source = build/'oracle.c'
        source.write_text(OBSERVER.replace('@HARNESS@', str(ROOT/'tools/nxu8/harness.c')))
        library = build/'oracle.so'
        subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
            '-shared', '-fPIC', str(source), str(ROOT/'tools/nxu8/vendor/SimU8/core.c'),
            '-o', str(library)], check=True)
        self.lib = C.CDLL(str(library))
        for name in ('harness_init', 'harness_ram', 'harness_set_pc', 'harness_get_pc',
            'harness_set_reg', 'harness_get_reg', 'harness_set_sp', 'harness_get_sp',
            'harness_set_lr'):
            getattr(self.lib, name).argtypes = getattr(self.machine.lib, name).argtypes
            getattr(self.lib, name).restype = getattr(self.machine.lib, name).restype
        self.machine.lib = self.lib
        self.machine.ram = self.lib.harness_ram().contents
        self.lib.table_observer_reset.argtypes = [C.c_uint64]
        self.lib.table_observer_run.argtypes = [C.c_uint64, C.c_uint32]
        self.lib.table_observer_mutation.argtypes = [C.c_uint64,
            C.POINTER(C.c_uint16), C.POINTER(C.c_uint8), C.c_uint]
        self.ram = self.machine.ram
        self.before_cb = ((C.c_uint8*65536)*64).in_dll(self.lib, 'table_cb_before')
        self.after_cb = ((C.c_uint8*65536)*64).in_dll(self.lib, 'table_cb_after')
        self.before_poll = ((C.c_uint8*65536)*64).in_dll(self.lib, 'table_poll_before')
        self.after_poll = ((C.c_uint8*65536)*64).in_dll(self.lib, 'table_poll_after')
        self.outputs = ((C.c_uint8*10)*64).in_dll(self.lib, 'table_cb_output')
        self.cb_status = (C.c_uint8*64).in_dll(self.lib, 'table_cb_status')
        self.cb_mode = (C.c_uint8*64).in_dll(self.lib, 'table_cb_mode')
        self.cb_continuation = (C.c_uint8*64).in_dll(self.lib, 'table_cb_continuation')
        self.cb_complete = (C.c_uint8*64).in_dll(self.lib, 'table_cb_complete')
        self.cb_begin = (C.c_uint16*64).in_dll(self.lib, 'table_cb_begin')
        self.cb_end = (C.c_uint16*64).in_dll(self.lib, 'table_cb_end')
        self.poll_status = (C.c_uint8*64).in_dll(self.lib, 'table_poll_status')
        self.poll_complete = (C.c_uint8*64).in_dll(self.lib, 'table_poll_complete')

    def count(self, name):
        return C.c_uint64.in_dll(self.lib, 'table_' + name).value

    def run(self, initial, pointer, cancel, limit, mutations=()):
        self.machine.reset(); C.memmove(self.ram, initial, 65536)
        self.machine.er(0, pointer); self.lib.harness_set_sp(0x8dee)
        self.lib.harness_set_lr(0x2fffe); self.lib.harness_set_pc(0x4f26)
        self.lib.table_observer_reset(cancel)
        if mutations:
            addresses = (C.c_uint16*len(mutations))(*[a for a, _ in mutations])
            values = (C.c_uint8*len(mutations))(*[v for _, v in mutations])
            self.lib.table_observer_mutation(1, addresses, values, len(mutations))
        run = self.lib.table_observer_run(limit, 0x2fffe)
        self.after = bytes(self.ram)
        floor = C.c_uint.in_dll(self.lib, 'table_minimum_sp').value
        return dict(run_status=run, native_status=self.machine.reg(0) if run == 100 else None,
            pc=f'{self.lib.harness_get_pc():06x}', minimum_sp=f'{floor:04x}',
            callback_count=self.count('callbacks'), poll_count=self.count('polls'),
            steps=self.count('steps'), final_ram_sha256=hashlib.sha256(self.after).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    parser.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    parser.add_argument('--predecessor', type=Path,
        default=ROOT/'analysis/native-fixtures/table-generation/predecessor-observations.jsonl.gz')
    parser.add_argument('--native-limit', type=int, default=5_000_000)
    parser.add_argument('--no-report', action='store_true',
        help='Write diagnostic observations without publishing the canonical report')
    args = parser.parse_args()
    if args.random_cases < 0 or args.native_limit < 1:
        parser.error('case count must be nonnegative and native limit positive')
    if not args.predecessor.is_file():
        parser.error('the original predecessor observation archive is required')
    build = ROOT/'analysis/build/table'; build.mkdir(parents=True, exist_ok=True)
    sources = ['csrc/table/fx_table.c', 'csrc/numeric/fx_numeric.c']
    inputs = implementation_inputs(ROOT, sources)
    pins = {name: sha(ROOT/name) for name in inputs}
    pins[str(Path(__file__))] = sha(Path(__file__))
    pins[str(args.predecessor)] = sha(args.predecessor)
    previous = None
    previous_path = ROOT/'analysis/c-verification/table-O2.json'
    if args.optimization == 'O3' and previous_path.is_file():
        previous = json.loads(previous_path.read_text())
        pins[str(previous_path)] = sha(previous_path)
    rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    for name in ('firmware/fx-991es-plus-c-ver4.bin', 'tools/nxu8/harness.c',
        'tools/nxu8/vendor/SimU8/core.c', 'analysis/disassembly/complete.asm'):
        pins[name] = sha(ROOT/name)
    library = build/f'table-{args.optimization}.so'
    subprocess.run(['gcc', '-std=c99', '-' + args.optimization,
        '-Wall', '-Wextra', '-Werror', '-pedantic', '-shared', '-fPIC', '-Wl,--no-undefined',
        *[str(ROOT/p) for p in sources], '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_table_generate.argtypes = [C.POINTER(C.c_uint8), C.c_uint16,
        C.POINTER(Control), C.POINTER(Result)]
    lib.fx_table_generate.restype = C.c_int
    lib.fx_rational_encode.argtypes = [C.POINTER(Number), C.POINTER(Rational)]
    lib.fx_rational_encode.restype = C.c_int
    native = Native(build, rom)
    pins[str(build/'oracle.c')] = sha(build/'oracle.c')
    pins[str(build/'oracle.so')] = sha(build/'oracle.so')
    pins[str(library)] = sha(library)
    failures = []; gaps = []; observations = []; cases = []; checks = 0
    counts = collections.Counter()

    def check(group, key, expected, actual, case_id):
        nonlocal checks
        checks += 1
        if expected != actual:
            failure = dict(case_id=case_id, group=group, key=key, expected=expected, actual=actual)
            failures.append(failure)
            if len(failures) <= 8:
                print(json.dumps(failure), flush=True)

    with gzip.open(args.predecessor, 'rt') as stream:
        for line in stream:
            old = json.loads(line)
            cases.append((bytes.fromhex(old['initial_ram']), 0x8190,
                old['cancel_at'], 'predecessor_' + old['group'], old))
    for functions in (0, 1, 2):
        for end in (0, 9, 19, 20, 29, 30, 99, 100):
            for selector in range(5):
                pointer = 0x9900 + selector
                cases.append((seed(b'X', 0, end, 1, functions, pointer=pointer),
                    pointer, 0, 'range_exponent_and_pointer', None))
    for expression in (b'X', b'X+1', b'X^2', b'1\x4fX', b'\x98X)', b'X+', b'(', b'X=2', b'X:3'):
        for functions in (0, 1):
            for phase in (0, 1, 0x80, 0x81):
                for cancel in (0, 1, 2):
                    cases.append((seed(expression, -1, 1, 1, functions, phase),
                        0x9900, cancel, 'expression_phase_cancel', None))
    # Native Start/End comparison rejects exact-form headers, while Step
    # admits a rational. Keep the actual format admission controls explicit.
    for index in range(3):
        for record in (bytes.fromhex('21a30000000000000301'),
            bytes.fromhex('80000001000201010100')):
            parameters = [decimal(0), decimal(3), decimal(1)]
            parameters[index] = record
            cases.append((seed(b'X', *parameters), 0x9900, 0, 'exact_parameter_admission', None))
    for record in (decimal(1, True), decimal('0.1', True), decimal(-1, True),
        bytes.fromhex('80020101000100010001'), bytes.fromhex('80000001000201010100')):
        cases.append((seed(b'X', 0, 1, record), 0x9900, 0, 'step_tag_admission', None))
    for numerator in (-7, -2, -1, 0, 1, 2, 7):
        for denominator in (1, 3, 7, 9):
            for flags in (0, 0x40):
                number = Number(); fraction = Rational(numerator, denominator, flags)
                # This supplies identical raw input bytes to both oracles;
                # no expected result is derived from the C constructor.
                assert lib.fx_rational_encode(C.byref(number), C.byref(fraction)) == 0
                for functions in (0, 1):
                    cases.append((seed(b'X', 0, 3, bytes(number), functions), 0x9900, 0,
                        'rational_step_conversion', None))
    for start, end, step in ((0, 1, '1e-100'), (0, 1, '1e-99'),
        (0, 1, '1e-2'), (0, '1e-100', 1), ('1e99', '2e99', '1e99'),
        ('-9e99', '9e99', '1e99'), (0, '1e-99', '1e99')):
        cases.append((seed(b'X', start, end, step), 0x9900, 0,
            'quotient_exponent_and_decimal_boundary', None))
    for pointer in (0x82ee, 0x82f8, 0x8276, 0x80de, 0x810e, 0x8138, 0x8125):
        for functions in (0, 1):
            cases.append((seed(b'X+1', 1, 3, 1, functions, pointer=pointer),
                pointer, 0, 'source_word_data_alias', None))
    for pointer in (0, 0x7fff, 0xffff):
        cases.append((seed(b'X', 1, 3, 1, pointer=pointer), pointer, 0,
            'source_word_bus_boundary', None))
    mutations = [
        [(0x810e, 1)], [(0x810e, 1), (0x8138, 1)],
        [(0x810e, 1), (0x8138, 0x81)], [(0x80de, 0)], [(0x80de, 1)],
        [(0x9900, 0x34), (0x9901, 0x12)],
        [(0x810e, 0), (0x8138, 1)]]
    for form in (decimal(0), decimal(2), decimal(-1), decimal(1, True), decimal('9e99'),
        bytes.fromhex('f3000000000000000000'), bytes.fromhex('f0000000000000000000'),
        bytes.fromhex('21a30000000000000301'), bytes.fromhex('61a30000000000000301'),
        bytes.fromhex('60000000000000000000'), bytes.fromhex('80000001000201010100')):
        mutations.append([(0x82b2+i, value) for i, value in enumerate(form)])
    mutations.append([(0x8276+i, value) for i, value in enumerate(decimal(9))])
    for mutation in mutations:
        cases.append((seed(b'X', 0, 2, 1), 0x9900, 0,
            'prepared_callback_live_effects', None, mutation))
    rng = random.Random(0x4f26)
    expressions = (b'X', b'X+1', b'X^2', b'1\x4fX', b'\x98X)', b'X+', b'(')
    for _ in range(args.random_cases):
        start = Decimal(rng.randint(-20, 20))/Decimal(10**rng.randrange(3))
        step = Decimal(rng.randint(1, 20))/Decimal(10**rng.randrange(3))
        end = start + step*Decimal(rng.randrange(35))
        functions = rng.randrange(2); phase = rng.choice((0, 1, 0x80, 0x81))
        pointer = 0x9900 + rng.randrange(5)
        cases.append((seed(rng.choice(expressions), start, end, step, functions, phase, pointer),
            pointer, rng.randrange(5), 'seeded_decimal', None))

    native_archive = build/f'original-observations-{args.optimization}.jsonl.gz'
    archive_stream = gzip.open(native_archive, 'wt')
    for case_id, case in enumerate(cases):
        initial, pointer, cancel, group, archived = case[:5]
        mutation = case[5] if len(case) > 5 else ()
        original = native.run(initial, pointer, cancel, args.native_limit, mutation)
        boundaries = []
        for j in range(min(original['callback_count'], 64)):
            entry, exit = bytes(native.before_cb[j]), bytes(native.after_cb[j])
            boundary = dict(kind='171EA_evaluator', index=j, complete=bool(native.cb_complete[j]),
                mode=native.cb_mode[j], continuation=native.cb_continuation[j],
                entry_source=f'{native.cb_begin[j]:04x}', entry_x=entry[0x8276:0x8280].hex(),
                entry_ram_sha256=hashlib.sha256(entry).hexdigest())
            if native.cb_complete[j]:
                boundary.update(return_source=f'{native.cb_end[j]:04x}',
                    native_status=native.cb_status[j], output_record=bytes(native.outputs[j]).hex(),
                    exit_ram_sha256=hashlib.sha256(exit).hexdigest(),
                    boundary_ram_differences=[(f'{i:04x}', a, b) for i, (a, b)
                        in enumerate(zip(entry, exit)) if a != b])
            boundaries.append(boundary)
        for j in range(min(original['poll_count'], 64)):
            entry, exit = bytes(native.before_poll[j]), bytes(native.after_poll[j])
            boundary = dict(kind='5550_between_rows', index=j,
                complete=bool(native.poll_complete[j]), entry_ram_sha256=hashlib.sha256(entry).hexdigest())
            if native.poll_complete[j]:
                boundary.update(native_status=native.poll_status[j],
                    exit_ram_sha256=hashlib.sha256(exit).hexdigest(),
                    boundary_ram_differences=[(f'{i:04x}', a, b) for i, (a, b)
                        in enumerate(zip(entry, exit)) if a != b])
            boundaries.append(boundary)
        archive_stream.write(json.dumps(dict(case_id=case_id, group=group,
            source_pointer_word=f'{pointer:04x}', cancel_at=cancel,
            prepared_callback_effects=[(f'{a:04x}', v) for a, v in mutation],
            initial_ram=initial.hex(), final_ram=native.after.hex(),
            native=original, boundaries=boundaries), separators=(',', ':')) + '\n')
        floor = int(original['minimum_sp'], 16)
        # Actual CPU frames, including private60-byte TABLE numeric workspace,
        # are outside the named API. No physical payload range is excluded.
        def persistent(address):
            return not 0x8000 <= address < 0x80dc and not floor <= address < 0x8dee
        indices = [i for i in range(65536) if persistent(i)]
        if archived:
            for key in ('run_status', 'native_status', 'pc', 'poll_count', 'callback_count', 'final_ram_sha256'):
                check(group, 'archive_replay_' + key, archived[key], original[key], case_id)
        ram = (C.c_uint8*65536).from_buffer_copy(initial)
        result = Result(); consumed = dict(callbacks=0, polls=0)

        def differences(expected, actual):
            return [(f'{i:04x}', expected[i], actual[i]) for i in indices if expected[i] != actual[i]]

        def apply_effects(before, after, address):
            target = C.cast(address, C.POINTER(C.c_uint8*65536)).contents
            for i in indices:
                if before[i] != after[i]:
                    target[i] = after[i]

        @Evaluate
        def evaluate(_userdata, address, mode, continuation, source, output):
            j = consumed['callbacks']; consumed['callbacks'] += 1
            if j >= original['callback_count'] or j >= 64:
                failures.append(dict(case_id=case_id, key='unexpected_callback', actual=j))
                return -3
            if not native.cb_complete[j]:
                return -3
            before, after = bytes(native.before_cb[j]), bytes(native.after_cb[j])
            actual = C.string_at(address, 65536)
            check(group, 'callback_mode_' + str(j), native.cb_mode[j], mode, case_id)
            check(group, 'callback_actual_TABLE_mode_' + str(j), 0x88, mode, case_id)
            check(group, 'callback_continuation_' + str(j), native.cb_continuation[j], continuation, case_id)
            check(group, 'callback_source_' + str(j), native.cb_begin[j], source[0], case_id)
            check(group, 'callback_persistent_input_' + str(j), [], differences(before, actual), case_id)
            apply_effects(before, after, address)
            C.memmove(output, bytes(native.outputs[j]), 10)
            source[0] = native.cb_end[j]
            return native.cb_status[j]

        @Poll
        def poll(_userdata, address):
            j = consumed['polls']; consumed['polls'] += 1
            if j >= original['poll_count'] or j >= 64:
                failures.append(dict(case_id=case_id, key='unexpected_poll', actual=j))
                return 1
            if not native.poll_complete[j]:
                return -3
            before, after = bytes(native.before_poll[j]), bytes(native.after_poll[j])
            check(group, 'poll_persistent_input_' + str(j), [],
                differences(before, C.string_at(address, 65536)), case_id)
            apply_effects(before, after, address)
            return native.poll_status[j]

        control = Control(evaluate, poll, None)
        status = lib.fx_table_generate(ram, pointer, C.byref(control), C.byref(result))
        actual = bytes(ram)
        observation = dict(case_id=case_id, group=group, pointer=f'{pointer:04x}',
            prepared_callback_effects=[(f'{a:04x}', v) for a, v in mutation],
            initial_ram_sha256=hashlib.sha256(initial).hexdigest(), native=original,
            host_status=status, host_result=dict(source=f'{result.source:04x}',
                planned_rows=result.planned_rows, evaluated_rows=result.evaluated_rows,
                committed_rows=result.committed_rows, polls=result.polls),
            candidate_ram_sha256=hashlib.sha256(actual).hexdigest(),
            raw_persistent_differences=differences(native.after, actual))
        observations.append(observation)
        counts[(group, original['run_status'], original['native_status'], status)] += 1
        if group == 'source_word_bus_boundary':
            gaps.append(observation)
            check(group, 'declared_host_gap', -3, status, case_id)
            check(group, 'host_gap_has_no_mutations', hashlib.sha256(initial).hexdigest(),
                hashlib.sha256(actual).hexdigest(), case_id)
        elif original['run_status'] != 100:
            gaps.append(observation)
        else:
            if status < 0:
                gaps.append(observation)
            check(group, 'status', original['native_status'], status, case_id)
            check(group, 'all_persistent_RAM_including_all16_payloads', [], observation['raw_persistent_differences'], case_id)
            check(group, 'callbacks_consumed', original['callback_count'], consumed['callbacks'], case_id)
            check(group, 'polls_consumed', original['poll_count'], consumed['polls'], case_id)
            check(group, 'source_word', int.from_bytes(native.after[pointer:pointer+2], 'little'), result.source, case_id)
    # A negative host callback is an implementation exception, not nativeFF
    # interpreted as signed-1. Compare its retained preparation against an
    # actual native171EA entry boundary, then apply only declared host effects.
    exception_seed = seed(b'X', 1, 3, 1)
    exception_native = native.run(exception_seed, 0x9900, 0, args.native_limit)
    exception_floor = int(exception_native['minimum_sp'], 16)
    exception_boundary = bytes(native.before_cb[0])
    archive_stream.write(json.dumps(dict(case_id='host_exception_native_boundary',
        scope='Actual original transaction and171EA entry; negative callback is host-only',
        initial_ram=exception_seed.hex(), final_ram=native.after.hex(), native=exception_native,
        callback_entry_ram=exception_boundary.hex()), separators=(',', ':')) + '\n')
    for exception in (-1, -3):
        exception_ram = (C.c_uint8*65536).from_buffer_copy(exception_seed)
        exception_result = Result(); exception_calls = []
        @Evaluate
        def exception_callback(_userdata, address, mode, continuation, source, _output):
            exception_calls.append((mode, continuation, source[0]))
            address[0x8125] = 0xaa
            source[0] = 0x8204
            return exception
        exception_control = Control(exception_callback, Poll(), None)
        exception_status = lib.fx_table_generate(exception_ram, 0x9900,
            C.byref(exception_control), C.byref(exception_result))
        expected = bytearray(exception_boundary)
        expected[0x8125] = 0xaa; expected[0x9900:0x9902] = (0x8204).to_bytes(2, 'little')
        actual = bytes(exception_ram)
        exception_differences = [(f'{i:04x}', expected[i], actual[i]) for i in range(65536)
            if expected[i] != actual[i] and not 0x8000 <= i < 0x80dc and
            not exception_floor <= i < 0x8dee]
        check('host_callback_exception', 'explicit_host_gap_' + str(exception), -3, exception_status, None)
        check('host_callback_exception', 'actual_preparation_and_retained_effects_' + str(exception),
            [], exception_differences, None)
        check('host_callback_exception', 'actual_TABLE_request_' + str(exception),
            [(0x88, 1, 0x8200)], exception_calls, None)
    archive_stream.close()
    guard_ram = (C.c_uint8*65536).from_buffer_copy(seed(b'X', 1, 3, 1))
    guard_before = bytes(guard_ram); guard_result = Result()
    guard_calls = []
    @Evaluate
    def never_evaluate(_userdata, _ram, _mode, _continuation, _source, _output):
        guard_calls.append('evaluate'); return -3
    @Poll
    def never_poll(_userdata, _ram):
        guard_calls.append('poll'); return 1
    guard_control = Control(never_evaluate, never_poll, None)
    no_evaluator = Control(Evaluate(), never_poll, None)
    for name, ram_argument, control_argument, result_argument in (
        ('null_ram', None, C.byref(guard_control), C.byref(guard_result)),
        ('null_control', guard_ram, None, C.byref(guard_result)),
        ('null_result', guard_ram, C.byref(guard_control), None),
        ('null_evaluator', guard_ram, C.byref(no_evaluator), C.byref(guard_result))):
        check('api_guard', name, -1,
            lib.fx_table_generate(ram_argument, 0x9900, control_argument, result_argument), None)
        check('api_guard', name + '_unchanged', hashlib.sha256(guard_before).hexdigest(),
            hashlib.sha256(bytes(guard_ram)).hexdigest(), None)
    guard_ram[0x80f9] = 0xc1; guard_before = bytes(guard_ram)
    check('api_guard', 'unsupported_mode_not_relabelled', -3,
        lib.fx_table_generate(guard_ram, 0x9900, C.byref(guard_control), C.byref(guard_result)), None)
    check('api_guard', 'unsupported_mode_unchanged', hashlib.sha256(guard_before).hexdigest(),
        hashlib.sha256(bytes(guard_ram)).hexdigest(), None)
    check('api_guard', 'no_callback_from_rejected_API', [], guard_calls, None)
    check('provenance', 'source_hashes_stable', pins,
        {name: sha(Path(name) if Path(name).is_absolute() else ROOT/name) for name in pins}, None)
    report = dict(scope=__doc__, optimization=args.optimization, cases=len(cases),
        checks=checks, failures=failures, unsupported=gaps,
        counts=[dict(group=g, native_run=r, native_status=n, host_status=h, cases=c)
            for (g, r, n, h), c in sorted(counts.items(), key=lambda item:str(item[0]))],
        source_sha256=pins, observations=observations,
        native_observations_path=str(native_archive), native_observations_sha256=sha(native_archive),
        native_execution_is_test_only=True, evaluator_mode_relabelled=False)
    report['original_entries'] = len(cases) + 1
    report['comparisons'] = checks
    report['observation_archives'] = dict(predecessor=dict(path=str(args.predecessor),
        sha256=pins[str(args.predecessor)], captured_before_compilation=True,
        rechecked_after_execution=True), native=dict(path=str(native_archive), sha256=sha(native_archive)))
    if previous is not None:
        matching_sources = all(previous.get('source_sha256', {}).get(name) == digest
            for name, digest in pins.items() if name in inputs or name in
            (str(Path(__file__)), str(args.predecessor),
             'firmware/fx-991es-plus-c-ver4.bin', 'analysis/disassembly/complete.asm'))
        if previous.get('failures') or previous.get('optimization') != 'O2' or not matching_sources:
            raise RuntimeError('The preceding O2 observations do not pin these sources; rerun O2 first')
        report['additional_optimization'] = dict(optimization='O2', path=str(previous_path),
            sha256=pins[str(previous_path)], cases=previous['cases'], checks=previous['checks'],
            native_observations_path=previous['native_observations_path'],
            native_observations_sha256=previous['native_observations_sha256'])
    destination = build/f'result-{args.optimization}.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    if not args.no_report and not failures:
        dependencies = inputs + ['tools/c_build_inputs.py',
            'csrc/table/manifest.json', 'csrc/table/understood_ranges.json',
            'analysis/native-fixtures/table-generation/manifest.json']
        if previous is not None:
            dependencies.append(str(previous_path.relative_to(ROOT)))
        if args.optimization == 'O2':
            write_report('analysis/c-verification/table-O2.json', report, dependencies, 'tools/test_table_c.py')
        write_report('analysis/c-verification/table.json', report, dependencies, 'tools/test_table_c.py')
    print(json.dumps(dict(cases=len(cases), checks=checks, failures=len(failures),
        unsupported=len(gaps), report=str(destination))), flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
