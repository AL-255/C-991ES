#!/usr/bin/env python3
"""Finite packed decimal adapters against unchanged original firmware.

Every expected value is computed by the original CPU during this run. Raw
records are numerical coordinates, not a CPU model in the C implementation.
GPL-3.0-or-later.
"""
import argparse
import ctypes as C
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from trace_natural_result import settings
from c_verification import write_report

SOURCES = ['csrc/numeric/fx_raw_decimal_parts.c',
           'csrc/numeric/fx_raw_decimal_divide.c',
           'csrc/numeric/fx_raw_decimal_multiply_add.c',
           'csrc/numeric/fx_raw_fraction_convert.c',
           'csrc/numeric/fx_raw_decimal_exp.c',
           'csrc/numeric/fx_numeric.c', 'csrc/numeric/fx_transcend.c']
ORACLE = r'''
#include "HARNESS_PATH"
struct fraction_stage {uint32_t pc;uint8_t workspace[48];};
struct fraction_stage fraction_stages[8];unsigned fraction_stage_count;
int fraction_conversion_run(uint64_t limit) {
 fraction_stage_count=0;
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();
  if(pc==0x1c27c)return 100;
  if(pc==0x19fb6||pc==0x1a03a||pc==0x1a014||pc==0x1a09a) {
   if(fraction_stage_count<8){struct fraction_stage *s=&fraction_stages[fraction_stage_count++];s->pc=pc;memcpy(s->workspace,ram+0x8000,48);}
  }
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
int raw_arithmetic_run(uint64_t limit) {
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();if(pc==0x1bdd0||pc==0x2fffe)return 100;
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
int raw_exp_argument_run(uint64_t limit) {
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();if(pc==0x1a9ba||pc==0x2fffe)return 100;
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
struct cycle_state {CoreRegister_t core;uint8_t ram[65536];};
static struct cycle_state cycle_states[8];
unsigned cycle_first,cycle_repeat;
size_t raw_cycle_core_size(void){return sizeof(CoreRegister_t);}
size_t raw_cycle_state_size(void){return sizeof(struct cycle_state);}
void *raw_cycle_state(void){return &cycle_states[cycle_first];}
int raw_add_cycle_run(uint64_t limit) {
 unsigned count=0;cycle_first=cycle_repeat=0;
 for(uint64_t i=0;i<limit;++i) {
  if(harness_get_pc()==0x1bc6c) {
   for(unsigned j=0;j<count;++j)
    if(!memcmp(&CoreRegister,&cycle_states[j].core,sizeof CoreRegister)&&!memcmp(ram,cycle_states[j].ram,sizeof ram)) {
     cycle_first=j;cycle_repeat=count;return 104;
    }
   if(count>=8)return 105;
   cycle_states[count].core=CoreRegister;memcpy(cycle_states[count].ram,ram,sizeof ram);++count;
  }
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
'''

class Number(C.Structure):
    _fields_ = [('bytes', C.c_uint8 * 10)]
class Parts(C.Structure):
    _fields_ = [('denominator', C.c_uint8 * 10), ('whole', C.c_uint8 * 10),
                ('middle', C.c_uint8 * 10), ('has_middle', C.c_uint8)]
class Stage(C.Structure):
    _fields_ = [('pc', C.c_uint32), ('workspace', C.c_uint8 * 48)]

def internal(value):
    return value[8:] + value[:8][::-1]
def external(value):
    return value[2:10][::-1] + value[:2]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--random-cases', type=int, default=20000)
    p.add_argument('--library', type=Path)
    p.add_argument('--no-report', action='store_true')
    a = p.parse_args()
    build = ROOT / 'analysis/build/raw_decimal'
    build.mkdir(parents=True, exist_ok=True)
    library = a.library or build / 'raw-decimal.so'
    if not a.library:
        subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-shared', '-fPIC',
                        *(str(ROOT / s) for s in SOURCES), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_raw_fraction_split.argtypes = [C.POINTER(Parts), C.POINTER(Number)]
    for name in ['fx_raw_decimal_normalize', 'fx_raw_decimal_cleanup']:
        getattr(lib, name).argtypes = [C.c_void_p]
    for name in ['fx_raw_decimal_product', 'fx_raw_decimal_sum',
                 'fx_raw_decimal_multiply', 'fx_raw_decimal_add',
                 'fx_raw_decimal_quotient', 'fx_raw_decimal_divide']:
        getattr(lib, name).argtypes = [C.c_void_p] * 3
    lib.fx_raw_fraction_convert.argtypes = [C.c_void_p, C.c_void_p]
    lib.fx_raw_decimal_exp.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint)]
    lib.fx_raw_decimal_exp_argument.argtypes = [C.c_void_p, C.POINTER(C.c_uint8), C.c_void_p]
    helper = build / 'raw-oracle.c'
    helper.write_text(ORACLE.replace('HARNESS_PATH', str(ROOT / 'tools/nxu8/harness.c')))
    oracle = build / 'oracle'
    oracle.mkdir(exist_ok=True)
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', str(helper),
                    str(ROOT / 'tools/nxu8/vendor/SimU8/core.c'), '-o',
                    str(oracle / 'nxu8-harness.so')], check=True)
    m = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), oracle)
    m.lib.fraction_conversion_run.argtypes = [C.c_uint64]
    m.lib.raw_arithmetic_run.argtypes = [C.c_uint64]
    m.lib.raw_exp_argument_run.argtypes = [C.c_uint64]
    m.lib.raw_add_cycle_run.argtypes = [C.c_uint64]
    m.lib.raw_cycle_state.restype = C.c_void_p
    m.lib.raw_cycle_state_size.restype = C.c_size_t
    m.lib.raw_cycle_core_size.restype = C.c_size_t
    stages = (Stage * 8).in_dll(m.lib, 'fraction_stages')
    stage_count = C.c_uint.in_dll(m.lib, 'fraction_stage_count')
    counts, failures, cycles, examples = {}, [], [], []
    native_calls = 0
    rng = random.Random(0x19f1a1c22e)

    def check(group, actual, expected, detail):
        counts[group] = counts.get(group, 0) + 1
        if actual != expected and len(failures) < 40:
            failures.append(dict(group=group, actual=actual, expected=expected, fixture=detail))
            print(json.dumps(failures[-1]))
    def put(address, data):
        for i, value in enumerate(data):m.ram[address + i] = value
    def prepare(entry):
        m.reset();settings(m)
        m.lib.harness_set_sp(0x8dee);m.lib.harness_set_lr(0x2fffe);m.lib.harness_set_pc(entry)
    def c_binary(name, left, right, alias):
        buf = (C.c_uint8 * 80)(*[0xee] * 80)
        for i, v in enumerate(left):buf[16 + i] = v
        for i, v in enumerate(right):buf[48 + i] = v
        offset = [0, 16, 48, 17, 49][alias]
        before = bytes(buf[offset:offset + 10])
        status = getattr(lib, name)(C.byref(buf, offset), C.byref(buf, 16), C.byref(buf, 48))
        return status, bytes(buf[offset:offset + 10]), before
    def arithmetic(left, right, operation, label):
        nonlocal native_calls
        pre, full, entry = {'multiply': ('product', 'multiply', 0x1b8ec),
                            'add': ('sum', 'add', 0x1bc4e),
                            'divide': ('quotient', 'divide', 0x1b7a2)}[operation]
        pre, full = 'fx_raw_decimal_' + pre, 'fx_raw_decimal_' + full
        a, b = internal(left), internal(right)
        detail = dict(label=label, operation=operation, left=left.hex(), right=right.hex())
        prepare(entry);put(0x8000, a);put(0x8010, b);native_calls += 1
        host, _, _ = c_binary(pre, a, b, 0)
        if host == -3:
            stop = m.lib.raw_add_cycle_run(3000000) if operation == 'add' else 103
            check('nonreturn-proof', stop, 104, detail)
            if stop == 104:
                state = C.string_at(m.lib.raw_cycle_state(), m.lib.raw_cycle_state_size())
                size = m.lib.raw_cycle_core_size()
                cycles.append(dict(detail, first=C.c_uint.in_dll(m.lib, 'cycle_first').value,
                    repeat=C.c_uint.in_dll(m.lib, 'cycle_repeat').value,
                    cpu_and_entire_ram_sha256=hashlib.sha256(state).hexdigest(),
                    core=state[:size].hex(), workspace=state[size + 0x8000:size + 0x8020].hex()))
            for name in [pre, full]:
                for alias in range(5):
                    status, result, before = c_binary(name, a, b, alias)
                    check('nonreturn-status', status, -3, dict(detail, alias=alias))
                    check('nonreturn-unmutated', result.hex(), before.hex(), dict(detail, alias=alias))
            return
        stop = m.lib.raw_arithmetic_run(3000000)
        # Error operands or a zero divisor return before normalization.
        if m.lib.harness_get_pc() != 0x1bdd0:
            check('arithmetic-early-return', m.lib.harness_get_pc(), 0x2fffe, detail)
        check('arithmetic-native-stop', stop, 100, detail)
        expected_pre = bytes(m.ram[0x8000:0x800a])
        if m.lib.harness_get_pc() == 0x1bdd0:
            check('arithmetic-native-final-stop', m.lib.harness_run(3000000, 0x2fffe, False), 100, detail)
        expected_full = bytes(m.ram[0x8000:0x800a])
        for name, expected in [(pre, expected_pre), (full, expected_full)]:
            for alias in range(5):
                status, result, _ = c_binary(name, a, b, alias)
                check('arithmetic-host', status, 0, dict(detail, alias=alias, function=name))
                check('arithmetic-record', result.hex(), expected.hex(), dict(detail, alias=alias, function=name))

    fixtures = []
    for sign in range(256):
        for exponent in [0, 1, 9, 10, 15, 16, 20, 99, 100, 144, 153, 160, 255]:
            for lead in [0, 1, 9, 15, 16, 160, 239, 240, 255]:
                fixtures.append(bytes([lead, 0, 0, 0, 0, 0, 0, 1, exponent, sign]))
    for shift in range(16):
        for sign in range(256):fixtures.append((1 << (shift * 4)).to_bytes(8, 'big') + bytes([20, sign]))
    fixtures += [bytes(rng.randrange(256) for _ in range(10)) for _ in range(4096)]
    for fixture in fixtures:
        prepare(0x1bdd0);put(0x8000, internal(fixture));native_calls += 1
        stop = m.lib.harness_run(10000, 0x2fffe, False)
        actual = (C.c_uint8 * 10).from_buffer_copy(internal(fixture))
        lib.fx_raw_decimal_normalize(actual)
        check('normalize-stop', stop, 100, fixture.hex())
        check('normalize-record', bytes(actual).hex(), bytes(m.ram[0x8000:0x800a]).hex(), fixture.hex())
    for tail in [0, 1, 9, 15, 16, 0x9990, 0x9991, 0x9999, 0xffff]:
        for sign in range(256):
            fixture = bytes([1, 2, 3, 4, 5, 6, tail >> 8, tail & 255, 20, sign])
            prepare(0x1a6da);put(0x8000, internal(fixture));native_calls += 1
            stop = m.lib.harness_run(10000, 0x2fffe, False)
            actual = (C.c_uint8 * 10).from_buffer_copy(internal(fixture));lib.fx_raw_decimal_cleanup(actual)
            check('cleanup-stop', stop, 100, fixture.hex())
            check('cleanup-record', bytes(actual).hex(), bytes(m.ram[0x8000:0x800a]).hex(), fixture.hex())
    for operation in ['multiply', 'add', 'divide']:
        for i in range(4096):
            left = bytes(rng.randrange(256) for _ in range(10))
            right = bytes(rng.randrange(256) for _ in range(10))
            if operation == 'divide':right = bytes([rng.randrange(1,16)]) + right[1:]
            arithmetic(left, right, operation, 'arbitrary-' + str(i))
        for digit in range(15):
            for nibble in range(16):
                left = bytearray.fromhex('01000000000000000001')
                byte = 7 - digit // 2;left[byte] |= nibble << (4 * (digit & 1))
                arithmetic(bytes(left), bytes.fromhex('09abcdef01234567151b'), operation, 'digit-' + str(digit) + '-' + str(nibble))
    templates = [bytes.fromhex(x) for x in [
        '64a20000000000000301', '641a2000000000000401', '64a1a200000000000501',
        '64a2a300000000000501', '64533563da9e9f2b07de', '64082a55de3d0167061b',
        '64ffffffffffffff0f01', '64000000000000000000', '64aaabacadaeafba0806',
        '640123456789abcd1401', '65fdd922136163e51251', '6835c3cf7c9cf9110fb9',
        '65a32e1337ec518a11b6', '66545dd3aded35740db6', '662f950dfb9b879c0f41']]
    rich = list(templates)
    for template in templates[:10]:
        for field in [8, 9]:
            for value in range(256):
                record = bytearray(template);record[field] = value
                for slot in [0, 4, 8]:record[0] = 0x60 | slot;rich.append(bytes(record))
    rich += [bytes([0x60 | rng.randrange(9)]) + bytes(rng.randrange(256) for _ in range(9)) for _ in range(a.random_cases)]
    for index, fixture in enumerate(rich):
        detail = dict(index=index, input=fixture.hex())
        prepare(0x1c22e);m.ram[0x80f9] = 6 + index % 2
        m.ram[0x80fa] = [0, 1, 7, 9, 15, 255][index % 6]
        tail = bytes((index + j * 17) & 255 for j in range(10))
        put(0x8900, fixture + tail);m.er(0, 0x8900);m.er(12, 0x8900);native_calls += 1
        stop = m.lib.fraction_conversion_run(3000000)
        check('conversion-stop', stop, 100, detail)
        if stop != 100:continue
        expected = external(bytes(m.ram[0x8000:0x800a]))
        parts = Parts();source = Number.from_buffer_copy(fixture)
        lib.fx_raw_fraction_split(C.byref(parts), C.byref(source))
        captured = {s.pc: bytes(s.workspace) for s in stages[:stage_count.value]}
        check('split-middle-present', bool(parts.has_middle), 0x1a014 in captured, detail)
        for name, pc, offset in [('denominator',0x19fb6,16), ('middle',0x1a014,32),
                                ('whole',0x1a03a if parts.has_middle else 0x1a09a,0)]:
            if name == 'middle' and not parts.has_middle:continue
            check('split-' + name, bytes(getattr(parts,name)).hex(), captured[pc][offset:offset+10].hex(), detail)
        for alias in [0, 12, 13, 11, 17]:
            buf = (C.c_uint8 * 40)(*[0xee] * 40)
            for i,v in enumerate(fixture):buf[12+i]=v
            host = lib.fx_raw_fraction_convert(C.byref(buf,alias), C.byref(buf,12))
            check('conversion-host', host, 0, dict(detail,alias=alias))
            check('conversion-record', bytes(buf[alias:alias+10]).hex(), expected.hex(), dict(detail,alias=alias))
        check('exp-argument-native-stop', m.lib.raw_exp_argument_run(3000000), 100, detail)
        if m.lib.harness_get_pc() == 0x1a9ba:
            argument = (C.c_uint8 * 10)();guard = C.c_uint8(99)
            converted = Number.from_buffer_copy(expected)
            host = lib.fx_raw_decimal_exp_argument(argument,C.byref(guard),C.byref(converted))
            check('exp-argument-host',host,0,detail)
            check('exp-argument-record',bytes(argument).hex(),bytes(m.ram[0x8000:0x800a]).hex(),detail)
            check('exp-argument-guard',guard.value,m.ram[0x8021],detail)
        check('exp-native-stop', m.lib.harness_run(3000000,0x2fffe,False), 100, detail)
        wanted, wanted_status = bytes(m.ram[0x8900:0x8914]), m.reg(0)
        for alias in [False, True]:
            operand = Number.from_buffer_copy(expected);result = operand if alias else Number()
            native_status = C.c_uint(99)
            host = lib.fx_raw_decimal_exp(C.byref(result), C.byref(operand), C.byref(native_status))
            check('exp-host', host, 0, dict(detail,alias=alias))
            check('exp-record20', (bytes(result)+tail).hex(), wanted.hex(), dict(detail,alias=alias))
            check('exp-status', native_status.value, wanted_status, dict(detail,alias=alias))
            if not alias:check('exp-input', bytes(operand).hex(), expected.hex(), detail)
        if len(examples)<20:examples.append(dict(detail,converted=expected.hex(),result20=wanted.hex(),native_status=wanted_status))
    report = dict(checks=sum(counts.values()), native_calls=native_calls, groups=counts,
                  failures=failures, nonreturn_cases=cycles, examples=examples,
                  scope='Finite packed decimal construction, normalization, cleanup, quotient/product/sum, unchecked rich fraction conversion and prepared exponential. Live original records/status and exact/partial aliases.',
                  limits=['Numerical value adapters only; parser, bank allocation and physical interrupt/timer state are owned separately.',
                          'Native raw-add non-return is identified by repetition of the complete architectural register state and every RAM byte at1BC6C; portable output remains untouched and returnsUNIMPLEMENTED.',
                          'Arbitrary unnormalized raw quotient states requiring more than 256 grouped-subtraction or divisor-restoration steps remain unresolved and outside the bounded prepared rich-field contract. The canonical native corpus is unchanged.'])
    if not failures and not a.no_report and not a.library:
        report=write_report('analysis/c-verification/raw_decimal.json',report,SOURCES+[x[:-2]+'.h' for x in SOURCES]+['csrc/numeric/fx_transcend_internal.h','csrc/numeric/fx_transcend_guarded.h','tools/trace_natural_result.py','tools/c_verification.py'],'tools/test_raw_decimal_c.py')
    (build/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v if k not in ['nonreturn_cases','examples'] else len(v) for k,v in report.items() if k!='tested_inputs_sha256'},indent=2))
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
