#!/usr/bin/env python3
"""Unfiltered original-ROM prepared rich unary operations versus high-level C.

All immutable prepared inputs are replayed through unchanged CPU instructions.
Native faults and finite implementation boundaries remain individually visible.
"""
import argparse
import base64
import collections
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import zlib

from c_build_inputs import implementation_inputs
from c_verification import ROOT, write_report

HERE = ROOT / 'analysis/build/eval-rich-unary'
ENTRY, STOP, SENTINEL = 0x16538, 0x16588, 0x2fffe
DIM_START, DIM_END = 0x80e0, 0x8100
PAYLOAD_START, PAYLOAD_END = 0x829e, 0x883e

SOURCES = ['parse/fx_eval_rich.c', 'parse/fx_eval_rich_unary.c', 'parse/fx_eval_rich_reduce.c', 'parse/fx_eval_surd_workspace.c', 'platform/fx_platform.c', 'platform/fx_result_classify.c', 'linalg/fx_linalg.c', 'complex/fx_complex_dispatch.c', 'complex/fx_complex.c', 'complex/fx_complex_angle.c', 'complex/fx_complex_round.c', 'numeric/fx_numeric.c', 'numeric/fx_transcend.c', 'numeric/fx_power.c', 'numeric/fx_root.c', 'numeric/fx_combinatorics.c', 'numeric/fx_logbase.c', 'trig/fx_trig.c', 'trig/fx_trig_math.c', 'trig/fx_trig_inverse.c', 'trig/fx_trig_hyperbolic.c', 'numeric/fx_raw_decimal_parts.c', 'numeric/fx_raw_decimal_divide.c', 'numeric/fx_raw_decimal_multiply_add.c', 'numeric/fx_raw_fraction_convert.c', 'numeric/fx_raw_decimal_exp.c']

ORACLE = r'''
/* Read-only ROM oracle prototype; test observation only, no arithmetic. */
#include "harness.c"
uint64_t unary_steps, unary_polls;
unsigned unary_minimum_sp;
uint16_t unary_pair;
uint64_t unary_cancel_at;
uint64_t unary_mutation_poll;
uint16_t unary_mutation_address;
unsigned unary_mutation_length;
uint8_t unary_mutation_bytes[40];
uint8_t unary_poll_pairs[4096][20];
uint32_t unary_poll_steps[4096];
void unary_observer_reset(uint16_t pair, uint64_t cancel_at) {
    unary_steps = unary_polls = 0;
    unary_minimum_sp = harness_get_sp();
    unary_pair = pair;
    unary_cancel_at = cancel_at;
    unary_mutation_poll = unary_mutation_length = 0;
    memset(unary_poll_pairs, 0, sizeof unary_poll_pairs);
    memset(unary_poll_steps, 0, sizeof unary_poll_steps);
}
void unary_observer_mutation(uint64_t poll, uint16_t address,
    const uint8_t *bytes, unsigned length) {
    if (length > sizeof unary_mutation_bytes) length = sizeof unary_mutation_bytes;
    unary_mutation_poll = poll;
    unary_mutation_address = address;
    unary_mutation_length = length;
    memcpy(unary_mutation_bytes, bytes, length);
}
int unary_observer_run(uint64_t limit, uint32_t stop) {
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t pc = harness_get_pc();
        unsigned sp = harness_get_sp();
        if (sp < unary_minimum_sp) unary_minimum_sp = sp;
        if (pc == stop) return 100;
        if (pc == 0x5564) {
            uint64_t index = unary_polls++;
            if (index < 4096) {
                for (unsigned byte = 0; byte < 20; ++byte)
                    unary_poll_pairs[index][byte] = ram[(uint16_t)(unary_pair + byte)];
                unary_poll_steps[index] = (uint32_t)unary_steps;
            }
            /* Explicit host timer sample, as existing linalg oracle does. */
            if (unary_polls == unary_mutation_poll)
                for (unsigned byte = 0; byte < unary_mutation_length; ++byte)
                    ram[(uint16_t)(unary_mutation_address + byte)] = unary_mutation_bytes[byte];
            ram[0x8e00] = unary_cancel_at && unary_polls == unary_cancel_at ? 2 : 0;
        }
        int status = harness_run(1, stop, false);
        ++unary_steps;
        if (status != 103) return status;
    }
    return 103;
}
'''

class NativeUnaryOracle:
    def __init__(self, library=None):
        self.rom = (ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
        library = Path(library) if library else HERE/'native-unary-oracle.so'
        self.library = library
        self.lib = C.CDLL(str(library))
        self.lib.harness_init.argtypes = [C.c_void_p,C.c_size_t]
        self.lib.harness_set_pc.argtypes = [C.c_uint32]
        self.lib.harness_get_pc.restype = C.c_uint32
        self.lib.harness_last_address.restype = C.c_uint32
        self.lib.harness_set_reg.argtypes = [C.c_uint,C.c_uint8]
        self.lib.harness_get_reg.argtypes = [C.c_uint]
        self.lib.harness_get_reg.restype = C.c_uint8
        self.lib.harness_set_sp.argtypes = [C.c_uint16]
        self.lib.harness_get_sp.restype = C.c_uint16
        self.lib.harness_set_lr.argtypes = [C.c_uint32]
        self.lib.harness_ram.restype = C.POINTER(C.c_uint8*65536)
        self.lib.harness_run.argtypes = [C.c_uint64,C.c_uint32,C.c_bool]
        self.lib.harness_callback.restype = C.c_uint32
        self.lib.harness_trace_open.argtypes = [C.c_char_p,C.c_bool]
        self.lib.unary_observer_reset.argtypes = [C.c_uint16,C.c_uint64]
        self.lib.unary_observer_mutation.argtypes = [C.c_uint64,C.c_uint16,C.c_void_p,C.c_uint]
        self.lib.unary_observer_run.argtypes = [C.c_uint64,C.c_uint32]
        self.ram = self.lib.harness_ram().contents
        self.writes = (C.c_uint64*65536).in_dll(self.lib,'ram_write_counts')
        self.counts = (C.c_uint64*0x18000).in_dll(self.lib,'execution_counts')
        self._rom_buffer = C.create_string_buffer(self.rom)
        self.reset()

    def reset(self):
        self.lib.harness_init(self._rom_buffer,len(self.rom))

    def reg(self,index,value=None):
        if value is not None: self.lib.harness_set_reg(index,value)
        return self.lib.harness_get_reg(index)

    def er(self,index,value=None):
        if value is not None:
            self.reg(index,value&255); self.reg(index+1,(value>>8)&255)
        return self.reg(index) | self.reg(index+1)<<8

    def data(self,address,length):
        return bytes(self.rom[a] if a<0x8000 else self.ram[a]
                     for a in ((address+i)&65535 for i in range(length)))

    def trace_open(self,path,reads=True):
        if self.lib.harness_trace_open(str(Path(path)).encode(),reads):
            raise OSError(path)

    def trace_close(self): self.lib.harness_trace_close()

    def prepare(self,seed,selector,pair=0x8900,registers=None,sp=0x8dee,cancel_at=0,mutation=None):
        if len(seed)!=65536: raise ValueError('seed must be exact64KiB')
        if not 0<=selector<=255 or not 0<=pair<=65535:
            raise ValueError('byte selector and uint16 pair required')
        self.reset(); C.memmove(self.ram,seed,65536)
        for index,value in (registers or {}).items(): self.reg(int(index),value)
        self.reg(1,selector); self.er(12,pair)
        self.lib.harness_set_sp(sp); self.lib.harness_set_lr(SENTINEL)
        self.lib.harness_set_pc(ENTRY)
        self.lib.unary_observer_reset(pair,cancel_at)
        if mutation:
            data = bytes.fromhex(mutation['record'])
            if not 0 < len(data) <= 40 or not 0 <= mutation['address'] < 65536:
                raise ValueError('Mutation requires a bounded actual RAM address and record')
            self.lib.unary_observer_mutation(mutation['poll'],mutation['address'],data,len(data))
        self.cancel_at = cancel_at
        self.before = bytes(self.ram)
        self.pair, self.selector, self.initial_sp = pair,selector,sp
        self.initial_registers = [self.reg(i) for i in range(16)]
        self.table_offset = 0x291e+((selector<<1)&255)
        self.leaf = 0x10000+int.from_bytes(self.rom[self.table_offset:self.table_offset+2],'little')

    def execute(self,limit=5000000):
        status = self.lib.unary_observer_run(limit,STOP)
        after = bytes(self.ram)
        polls = C.c_uint64.in_dll(self.lib,'unary_polls').value
        samples = ((C.c_uint8*20)*4096).in_dll(self.lib,'unary_poll_pairs')
        sample_steps = (C.c_uint32*4096).in_dll(self.lib,'unary_poll_steps')
        differences = [(f'{i:04x}',a,b) for i,(a,b) in enumerate(zip(self.before,after)) if a!=b]
        touched = [(f'{i:04x}',self.writes[i]) for i in range(65536) if self.writes[i]]
        executed = [(f'{i*2:06x}',self.counts[i]) for i in range(len(self.counts)) if self.counts[i]]
        answer = {
            'entry':f'{ENTRY:06x}','stop':f'{STOP:06x}',
            'run_status':status,'pc':f'{self.lib.harness_get_pc():06x}',
            'last_pc':f'{self.lib.harness_last_address():06x}',
            'native_status':self.reg(0) if status==100 else None,
            'r2_before_16588':self.reg(2),
            'selector':self.selector,'table_offset':f'{self.table_offset:04x}','leaf':f'{self.leaf:06x}',
            'pair_address':f'{self.pair:04x}',
            'current20':self.data(self.pair,20).hex(),
            'other20':self.data((self.pair+20)&65535,20).hex(),
            'dimensions32':after[DIM_START:DIM_END].hex(),
            'payload1440':after[PAYLOAD_START:PAYLOAD_END].hex(),
            'dimensions_before32':self.before[DIM_START:DIM_END].hex(),
            'payload_before1440':self.before[PAYLOAD_START:PAYLOAD_END].hex(),
            'mask_before':self.before[0x8125],'mask_after':after[0x8125],
            'cancel_at':self.cancel_at,'poll_count':polls,'poll_samples':[bytes(samples[i]).hex() for i in range(min(polls,4096))],
            'poll_steps':[sample_steps[i] for i in range(min(polls,4096))],
            'poll_samples_truncated':polls>4096,
            'steps':C.c_uint64.in_dll(self.lib,'unary_steps').value,
            'minimum_sp':f'{C.c_uint.in_dll(self.lib,"unary_minimum_sp").value:04x}',
            'initial_sp':f'{self.initial_sp:04x}','final_sp':f'{self.lib.harness_get_sp():04x}',
            'initial_registers':self.initial_registers,'registers':[self.reg(i) for i in range(16)],
            'context_before':self.before[0x80f0:0x8140].hex(),
            'context_after':after[0x80f0:0x8140].hex(),
            'ram_changes':differences,'ram_writes':touched,'executed_instructions':executed,
            'initial_ram_sha256':hashlib.sha256(self.before).hexdigest(),
            'final_ram_sha256':hashlib.sha256(after).hexdigest(),
            'callback':self.lib.harness_callback(),
            'provenance':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                ROOT/'firmware/fx-991es-plus-c-ver4.bin',HERE/'native_unary_oracle.c',
                Path(__file__),self.library,ROOT/'tools/nxu8/harness.c',
                ROOT/'tools/nxu8/vendor/SimU8/core.c',ROOT/'tools/nxu8/vendor/SimU8/core.h',
                ROOT/'tools/nxu8/vendor/SimU8/mmu.h')},
            'timer_policy':'Direct host injection RAM8E00=2 at requested cancel poll, otherwise0, immediately before original5564; not a simulated CPU write.',
            'boundary_policy':'Stops before original16588 copies R0 toR2; native_status isR0, no outer16336 frame needed.'
        }
        self.after = after
        return answer

    def run(self,seed,selector,pair=0x8900,registers=None,sp=0x8dee,limit=5000000,cancel_at=0,mutation=None):
        self.prepare(seed,selector,pair,registers,sp,cancel_at,mutation)
        return self.execute(limit)


FIXTURE = 'analysis/native-fixtures/eval-rich/unary/observations.json'
LIMITS = 'analysis/native-fixtures/eval-rich/unary/unsupported.json'

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]

class Complex(C.Structure):
    _fields_ = [('real', Number), ('imaginary', Number)]

class Storage(C.Structure):
    _fields_ = [('ram', C.POINTER(C.c_uint8)), ('ram_size', C.c_size_t),
                ('rom', C.POINTER(C.c_uint8)), ('rom_size', C.c_size_t)]

class NumericContext(C.Structure):
    _fields_ = [('exact_math', C.c_uint8), ('display_mode', C.c_uint8),
                ('digits', C.c_uint8), ('cancel_at', C.c_uint32)]

class Context(C.Structure):
    _fields_ = [('calculation_context', C.c_uint8), ('numeric', NumericContext),
                ('cancelled', C.c_void_p), ('userdata', C.c_void_p)]

class Result(C.Structure):
    _fields_ = [('value', Complex), ('other', Complex),
                ('native_status', C.c_uint8), ('cancellation_checks', C.c_uint32)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_blob(value):
    return zlib.decompress(base64.b64decode(value, validate=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-report', action='store_true')
    parser.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    args = parser.parse_args()
    HERE.mkdir(parents=True, exist_ok=True)
    fixture = json.loads((ROOT / FIXTURE).read_text())
    declared = {row['case_id']: row for row in json.loads((ROOT / LIMITS).read_text())['cases']}
    source_names = ['csrc/' + source for source in SOURCES]
    inputs = implementation_inputs(ROOT, source_names)
    inputs += [FIXTURE, LIMITS, 'tools/c_build_inputs.py', 'tools/c_verification.py',
               str(Path(__file__).resolve().relative_to(ROOT))]
    inputs += ['tools/nxu8/harness.c', 'tools/nxu8/vendor/SimU8/core.c',
               'firmware/fx-991es-plus-c-ver4.bin']
    inputs += [str(path.relative_to(ROOT)) for path in
               (ROOT / 'tools/nxu8/vendor/SimU8').glob('*.h')]
    before = {name: digest(ROOT / name) for name in sorted(set(inputs))}
    rom_bytes = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    if hashlib.sha256(rom_bytes).hexdigest() != fixture['firmware_sha256']:
        raise ValueError('Fixture firmware digest changed')
    oracle_source = HERE / 'native_unary_oracle.c'
    oracle_source.write_text(ORACLE)
    # Recompile every original oracle invocation; headers cannot silently use
    # a cached CPU library built before their pinned revision.
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', '-I', str(ROOT / 'tools/nxu8'), str(oracle_source),
        str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'),
        '-o', str(HERE / 'native-unary-oracle.so')], check=True)
    shared = HERE / 'rich-unary.so'
    subprocess.run(['gcc', '-std=c99', '-' + args.optimization,
        '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-Wl,--no-undefined',
        *[str(ROOT / name) for name in source_names], '-o', str(shared)], check=True)
    lib = C.CDLL(str(shared))
    lib.fx_eval_rich_unary_after_storage.argtypes = [C.POINTER(Result), C.POINTER(Storage),
        C.POINTER(Complex), C.POINTER(Complex), C.c_uint8, C.POINTER(Context), C.c_uint16]
    native = NativeUnaryOracle()
    rom = (C.c_uint8 * len(rom_bytes)).from_buffer_copy(rom_bytes)
    failures = []
    counts = collections.Counter()
    groups = collections.Counter()
    boundaries = []

    def check(key, expected, actual, case_id):
        counts['checks'] += 1
        if expected != actual:
            failure = dict(case_id=case_id, field=key, expected=expected, actual=actual)
            failures.append(failure)
            if len(failures) <= 12:
                print(json.dumps({k: v for k, v in failure.items() if k not in ('expected', 'actual')}), flush=True)

    for row in fixture['cases']:
        case_id = row['case_id']
        seed = decode_blob(row['initial_ram_zlib_base64'])
        check('seed_exact_64KiB', 65536, len(seed), case_id)
        check('seed_digest', row['initial_ram_sha256'], hashlib.sha256(seed).hexdigest(), case_id)
        packed_original = decode_blob(row['original_observation_zlib_base64'])
        check('original_archive_digest', row['original_observation_sha256'],
              hashlib.sha256(packed_original).hexdigest(), case_id)
        original = json.loads(packed_original)
        expected = native.run(seed, row['selector'], pair=row['pair'],
            registers=dict(enumerate(row['registers'])), sp=row['sp'],
            cancel_at=row['cancel_at'], limit=row['limit'],mutation=row.get('callback_mutation'))
        expected['ram_changes'] = [list(item) for item in expected['ram_changes']]
        expected['ram_writes'] = [list(item) for item in expected['ram_writes']]
        for key in fixture['native_replay_fields']:
            check('original_replay_' + key, original[key], expected[key], case_id)
        counts['native_calls'] += 1
        ram = (C.c_uint8 * 65536).from_buffer_copy(seed)
        storage = Storage(ram, 65536, rom, len(rom_bytes))
        pair = row['pair']
        current = Complex.from_buffer_copy(seed[pair:pair+20])
        other = Complex.from_buffer_copy(seed[pair+20:pair+40])
        output = Result()
        exact = bool(seed[0x80f9] & 0x40 and seed[0x8106] and seed[0x810c] != 1 and
                     not (seed[0x80fc] & 0x40) and seed[0x80f5] != 0xed and
                     not (seed[0x8124] & 1))
        callback_calls = [0]
        callback = None
        if row.get('callback_mutation'):
            mutation = row['callback_mutation']
            def mutate(_userdata):
                callback_calls[0] += 1
                if callback_calls[0] == mutation['poll']:
                    record = bytes.fromhex(mutation['record'])
                    ram[mutation['address']:mutation['address']+len(record)] = record
                return 0
            callback = C.CFUNCTYPE(C.c_int,C.c_void_p)(mutate)
        context = Context(seed[0x80f9], NumericContext(exact, 0, 0, row['cancel_at']),
                          C.cast(callback,C.c_void_p) if callback else None,None)
        host = lib.fx_eval_rich_unary_after_storage(C.byref(output), C.byref(storage),
            C.byref(current), C.byref(other), row['selector'], C.byref(context), 0)
        counts['cases'] += 1
        if callback:
            counts['callback_mutation_cases'] += 1
            check('callback_actual_invocations',expected['poll_count'],callback_calls[0],case_id)
            regression = row['regression']
            check('callback_native_F3_current20',regression['native_current20'],
                  bytes(output.value).hex(),case_id)
            check('callback_native_F3_cell10',regression['native_cell10'],
                  bytes(ram[mutation['address']:mutation['address']+10]).hex(),case_id)
        groups[(row['origin']['archive'], host, expected['run_status'])] += 1
        if case_id in declared:
            limit = declared[case_id]
            check('declared_host_limit', limit['host_status'], host, case_id)
            check('declared_native_boundary', limit['native_run_status'], expected['run_status'], case_id)
            check('declared_native_status', limit['native_status'], expected['native_status'], case_id)
            check('declared_native_PC', limit['native_pc'], expected['pc'], case_id)
            check('declared_complete_native_RAM', limit['native_final_ram_sha256'],
                  expected['final_ram_sha256'], case_id)
            category = 'native_boundaries' if expected['run_status'] != 100 else 'host_gaps'
            counts[category] += 1
            boundaries.append(limit)
        else:
            check('handled_host_status', 0, host, case_id)
            check('handled_native_return', 100, expected['run_status'], case_id)
            if host == 0 and expected['run_status'] == 100:
                counts['handled'] += 1
                actual = bytearray(bytes(ram))
                actual[pair:pair+40] = bytes(output.value) + bytes(output.other)
                check('current20', expected['current20'], bytes(output.value).hex(), case_id)
                check('other20', expected['other20'], bytes(output.other).hex(), case_id)
                check('native_R0', expected['native_status'], output.native_status, case_id)
                check('actual_poll_count', expected['poll_count'], output.cancellation_checks, case_id)
                check('physical_dimensions32', expected['dimensions32'], actual[0x80e0:0x8100].hex(), case_id)
                check('physical_payload1440', expected['payload1440'], actual[0x829e:0x883e].hex(), case_id)
                check('temporary_mask', expected['mask_after'], actual[0x8125], case_id)
                frame = {int(address, 16) for address, count in expected['ram_writes']
                         if count and int(expected['minimum_sp'], 16) <= int(address, 16) < row['sp']}
                differences = [(f'{address:04x}', wanted, found)
                    for address, (wanted, found) in enumerate(zip(native.after, actual))
                    if wanted != found and not 0x8000 <= address < 0x80dc and address not in frame]
                check('persistent_RAM_including_pool_and_MMIO', [], differences, case_id)
        if counts['cases'] % 1000 == 0:
            print('ORIGINAL', counts['cases'], flush=True)
    check('all_unfiltered_observations', fixture['case_count'], counts['cases'], None)
    check('all_declared_limits_replayed', len(declared), len(boundaries), None)
    after = {name: digest(ROOT / name) for name in before}
    if before != after:
        raise RuntimeError('An implementation/oracle/fixture input changed; rerun this suite')
    report = dict(suite='eval_rich_unary', counts=dict(counts), cases=counts['cases'],
        native_calls=counts['native_calls'], comparisons=counts['checks'],
        failures=failures, bounded_original_cases=boundaries,
        groups=[dict(archive=key[0], host_status=key[1], native_run_status=key[2], cases=count)
                for key, count in sorted(groups.items())],
        scope='Original16538 mapped unary stage after storage; complete20-byte current/other, R0, real poll count, all16 physical dimensions/payload/mask and persistent RAM.',
        limits=['8000..80DB numerical working bytes and only individually witnessed CPU frame write addresses are excluded from C RAM parity; every pool byte8640..87CF and timer/MMIO byte remains compared.',
                'Every native fault/instruction-limit outcome and every finite native unsupported domain is retained, replayed and pinned in unsupported.json; no finite case is silently omitted.',
                'Standalone pointer API uses private host work records. Actual physical work-record cancellation callback snapshots are exercised by test_eval_rich_c.py; allocation/parser staging remain caller-owned.',
                'Native wide square/product CPU-buffer execution, bounded giant-vector traversal, observed fault/instruction-limit outcomes, C4 round frame overflow, precision>9, and opposed-surds/round sources overlapping8640..867B retain explicit host boundaries.'],
        compiler_optimization=args.optimization,
        actual_compiled_artifacts_sha256={str(path.relative_to(ROOT)): digest(path)
            for path in (shared, HERE/'native-unary-oracle.so', oracle_source)})
    if not args.no_report and not failures:
        write_report('analysis/c-verification/eval_rich_unary.json', report, inputs,
                     'tools/test_eval_rich_unary_c.py')
    if failures:
        (HERE / 'failures.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(counts=dict(counts), failures=len(failures)), indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
