#!/usr/bin/env python3
"""Compare high-level special-result recognition with the native wrapper stage.

This tests replacement of an already computed trigonometric decimal result.
It does not test a C sine/cosine/tangent implementation or angle reduction.
GPL-3.0-or-later.
"""
import ctypes as C
import decimal
import json
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


def oracle(machine, record, function, exact):
    machine.reset(); settings(machine)
    machine.ram[0x8106] = exact
    for i, value in enumerate(record): machine.ram[0x8300 + i] = value
    # Reproduce the stack immediately after numeric trig returns: the saved
    # record pointer followed by the wrapper's saved large-model returnPC.
    machine.word(0x8de8, 0x8300); machine.word(0x8dea, 0xfffe)
    machine.ram[0x8dec] = 2
    machine.reg(0, 0); machine.reg(11, 0)
    machine.lib.harness_set_sp(0x8de8)
    machine.lib.harness_set_pc(0x16318 if function == 2 else 0x1627a)
    status = machine.lib.harness_run(1000000, 0x2fffe, False)
    assert status == 100, (status, hex(machine.lib.harness_get_pc()))
    return bytes(machine.ram[0x8300:0x830a]), bool(machine.counts[0x162de // 2])


def decimal_value(record):
    digits = str(record[0] & 15) + ''.join(f'{value:02x}' for value in record[1:8])
    exponent = (record[8] >> 4) * 10 + (record[8] & 15)
    if record[9] % 5 == 0: exponent -= 100
    return decimal.Decimal(int(digits)) * decimal.Decimal(10) ** (exponent - 14)


def main():
    directory = ROOT / 'analysis/build/trig'
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / 'trig.so'
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', str(ROOT / 'csrc/trig/fx_trig.c'),
                    str(ROOT / 'csrc/numeric/fx_numeric.c'), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_trig_special_result.argtypes = [C.POINTER(Number), C.POINTER(Number),
                                          C.c_int, C.c_int, C.POINTER(C.c_uint)]
    lib.fx_decimal_parse.argtypes = [C.POINTER(Number), C.c_char_p]
    machine = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), directory / 'oracle')
    fixture = json.loads((ROOT / 'analysis/special-angle-trace/manifest.json').read_text())
    cases = []
    for row in fixture['cases']:
        if row['numeric_record_before_table'] is None: continue
        function = 2 if row['name'].startswith('tan') else 1 if row['name'].startswith('cos') else 0
        cases.append((row['name'], bytes.fromhex(row['numeric_record_before_table']),
                      function, row['math_output_8106']))
    with decimal.localcontext() as context:
        context.prec = 50
        for i, row in enumerate(fixture['tables']):
            value = decimal_value(bytes.fromhex(row['numeric_record']))
            threshold = decimal.Decimal('5e-12' if i >= 7 else '5e-13')
            for sign in [-1, 1]:
                for scale in ['-1.0001','-1','-.9999','-.5','0','.5','.9999','1','1.0001']:
                    number = Number()
                    literal = str(sign * (value + decimal.Decimal(scale) * threshold))
                    assert lib.fx_decimal_parse(C.byref(number), literal.encode()) == 0
                    for exact in [0, 1]:
                        for function in ([0, 1] if row['family'] == 'sin/cos' else [2]):
                            cases.append((f'boundary-{i}-{sign}-{scale}-{exact}-{function}',
                                          bytes(number.bytes), function, exact))
        randomizer = random.Random(16298)
        for i in range(1000):
            value = decimal.Decimal(randomizer.randrange(-1000000000000000,1000000000000000))
            value *= decimal.Decimal(10) ** randomizer.randrange(-28,-10)
            number = Number(); assert lib.fx_decimal_parse(C.byref(number), str(value).encode()) == 0
            cases.append((f'random-{i}', bytes(number.bytes), i%3, i%2))
    failures = []
    aliases = 0
    for name, record, function, exact in cases:
        number = Number.from_buffer_copy(record); output = Number(); matched = C.c_uint()
        status = lib.fx_trig_special_result(C.byref(output), C.byref(number), function, exact, C.byref(matched))
        expected, native_match = oracle(machine, record, function, exact)
        if status or bytes(output.bytes) != expected or bool(matched.value) != native_match or bytes(number.bytes) != record:
            failures.append({'name': name, 'input': record.hex(), 'function': function, 'exact': exact,
                             'status': status, 'actual': bytes(output.bytes).hex(),
                             'expected': expected.hex(), 'matched': [matched.value, native_match]})
        if aliases < 100:
            status = lib.fx_trig_special_result(C.byref(number), C.byref(number), function, exact, None)
            assert status == 0 and bytes(number.bytes) == bytes(output.bytes)
            aliases += 1
    report = {'cases': len(cases), 'failures': len(failures), 'mismatches': failures,
              'alias_cases': aliases,
              'scope': 'native1627A/16318 special-result replacement stage after prepared numeric trig results',
              'limitation': 'numeric trig cores, angle reduction and complete evaluator I/O are not covered'}
    path = ROOT / 'analysis/c-verification/trig.json'
    if failures:
        report['status'] = 'fail'; path.write_text(json.dumps(report, indent=2) + '\n')
    else:
        write_report(path, report, ['csrc/trig/fx_trig.c','csrc/trig/fx_trig.h',
                                   'csrc/numeric/fx_numeric.c','csrc/numeric/fx_numeric.h',
                                   'tools/trace_natural_result.py', 'tools/c_verification.py',
                                   'analysis/special-angle-trace/manifest.json'], 'tools/test_trig_c.py')
    print(f'{len(cases)} special-result cases, {len(failures)} mismatches')
    for failure in failures[:12]: print(failure)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
